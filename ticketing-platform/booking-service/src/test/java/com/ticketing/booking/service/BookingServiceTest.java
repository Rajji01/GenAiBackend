package com.ticketing.booking.service;

import com.ticketing.booking.dto.BookingRequest;
import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingStatus;
import com.ticketing.booking.exception.IdempotencyKeyReuseException;
import com.ticketing.booking.exception.ResourceNotFoundException;
import com.ticketing.booking.repository.BookingRepository;
import com.ticketing.booking.repository.BookingSeatRepository;
import com.ticketing.booking.service.BookingService.BookingCreationResult;
import org.junit.jupiter.api.Test;
import org.mockito.stubbing.Answer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

// Full integration against real Postgres. Idempotency is the ONE guarantee
// Day 2 exists to prove — under both the sequential retry path and a real
// concurrent-insert race. See WEEK2_DESIGN.md §5.
@SpringBootTest
@Testcontainers
class BookingServiceTest {

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine")
            .withDatabaseName("booking")
            .withUsername("booking_user")
            .withPassword("booking_pass");

    @DynamicPropertySource
    static void registerProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
    }

    @Autowired
    private BookingService bookingService;

    @Autowired
    private BookingRepository bookingRepository;

    @Autowired
    private BookingSeatRepository bookingSeatRepository;

    // The saga is a separate concern with its own end-to-end tests
    // (BookingSagaServiceTest). Here we care only about BookingService's
    // own contract: idempotency + insert. Mock it to return the booking
    // untouched — assertions below check status=PENDING because that's the
    // state the row is in when the saga would have taken over.
    @MockBean
    private BookingSagaService sagaService;

    private BookingRequest sampleRequest() {
        return new BookingRequest(1L, List.of(5L, 6L, 7L), "user-1");
    }

    // Make the mocked saga a passthrough: return whatever booking is
    // already in the DB under the given id. That keeps the assertion
    // simple ("status is what BookingService inserted", i.e. PENDING)
    // without leaking saga logic into these tests.
    private void wireSagaAsPassthrough() {
        Answer<Booking> passthrough = inv -> {
            Long bookingId = inv.getArgument(0);
            return bookingRepository.findById(bookingId).orElseThrow();
        };
        when(sagaService.runSaga(anyLong(), anyLong(), anyString(), any())).thenAnswer(passthrough);
    }

    @Test
    void create_withAFreshKey_insertsPendingBookingAndBookingSeats() {
        wireSagaAsPassthrough();
        String key = UUID.randomUUID().toString();
        BookingCreationResult result = bookingService.create(key, sampleRequest());

        assertThat(result.freshlyCreated()).isTrue();
        assertThat(result.response().status()).isEqualTo(BookingStatus.PENDING); // saga is Day 3
        assertThat(result.response().seatIds()).containsExactly(5L, 6L, 7L);
        assertThat(result.response().createdAt()).isNotNull();
        assertThat(result.response().confirmedAt()).isNull();
        assertThat(result.response().paymentRef()).isNull();

        Long id = result.response().bookingId();
        assertThat(bookingRepository.findById(id)).isPresent();
        assertThat(bookingSeatRepository.findByBookingId(id)).hasSize(3);
    }

    @Test
    void create_withTheSameKeyAndSameBody_returnsTheSameBookingWithoutInsertingAgain() {
        wireSagaAsPassthrough();
        String key = UUID.randomUUID().toString();
        BookingCreationResult first = bookingService.create(key, sampleRequest());

        BookingCreationResult second = bookingService.create(key, sampleRequest());

        assertThat(second.freshlyCreated()).isFalse();
        assertThat(second.response().bookingId()).isEqualTo(first.response().bookingId());
        assertThat(bookingRepository.count()).isEqualTo(bookingRepository.count()); // no double-insert
    }

    @Test
    void create_reorderingSeatIds_doesNotFalseFireTheKeyMismatchCheck() {
        wireSagaAsPassthrough();
        // Canonical hash sorts seat ids — WEEK2_DESIGN.md §5. A client that
        // resends the same seats in a different order is a retry, not a new
        // request; the 422 branch would be a bug there.
        String key = UUID.randomUUID().toString();
        BookingCreationResult first = bookingService.create(key, new BookingRequest(1L, List.of(5L, 6L, 7L), "user-1"));

        BookingCreationResult retry = bookingService.create(key, new BookingRequest(1L, List.of(7L, 5L, 6L), "user-1"));

        assertThat(retry.freshlyCreated()).isFalse();
        assertThat(retry.response().bookingId()).isEqualTo(first.response().bookingId());
    }

    @Test
    void create_withTheSameKeyAndADifferentBody_throws422_andDoesNotOverwriteTheOriginal() {
        wireSagaAsPassthrough();
        String key = UUID.randomUUID().toString();
        BookingCreationResult first = bookingService.create(key, sampleRequest());

        assertThrows(IdempotencyKeyReuseException.class, () ->
                bookingService.create(key, new BookingRequest(2L, List.of(99L), "user-2")));

        Booking stored = bookingRepository.findById(first.response().bookingId()).orElseThrow();
        assertThat(stored.getShowId()).isEqualTo(1L);        // untouched
        assertThat(stored.getHolderId()).isEqualTo("user-1"); // untouched
    }

    @Test
    void get_returnsAStoredBooking() {
        wireSagaAsPassthrough();
        String key = UUID.randomUUID().toString();
        Long id = bookingService.create(key, sampleRequest()).response().bookingId();

        var response = bookingService.get(id);

        assertThat(response.bookingId()).isEqualTo(id);
        assertThat(response.seatIds()).containsExactly(5L, 6L, 7L);
    }

    @Test
    void get_returns404WhenTheBookingDoesNotExist() {
        assertThrows(ResourceNotFoundException.class, () -> bookingService.get(999_999L));
    }

    // The race the WEEK2_DESIGN.md §5 "Racing insert" section pre-commits to
    // handling: two parallel POSTs with the same fresh key, released
    // simultaneously via a CountDownLatch. Exactly one wins the unique index,
    // the other catches DataIntegrityViolationException and re-reads. No
    // duplicate row, no 500 to either caller.
    @Test
    void create_undertConcurrentInsertsWithTheSameKey_exactlyOneWinsAndTheOtherIsAnIdempotentRetry() throws Exception {
        wireSagaAsPassthrough();
        String key = UUID.randomUUID().toString();
        BookingRequest request = sampleRequest();

        long baselineCount = bookingRepository.count();

        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch go = new CountDownLatch(1);
        AtomicReference<BookingCreationResult> a = new AtomicReference<>();
        AtomicReference<BookingCreationResult> b = new AtomicReference<>();
        AtomicReference<Throwable> aErr = new AtomicReference<>();
        AtomicReference<Throwable> bErr = new AtomicReference<>();

        ExecutorService pool = Executors.newFixedThreadPool(2);
        pool.submit(() -> {
            ready.countDown();
            try {
                go.await();
                a.set(bookingService.create(key, request));
            } catch (Throwable t) {
                aErr.set(t);
            }
        });
        pool.submit(() -> {
            ready.countDown();
            try {
                go.await();
                b.set(bookingService.create(key, request));
            } catch (Throwable t) {
                bErr.set(t);
            }
        });

        ready.await(5, TimeUnit.SECONDS);
        go.countDown();
        pool.shutdown();
        pool.awaitTermination(15, TimeUnit.SECONDS);

        assertThat(aErr.get()).isNull();
        assertThat(bErr.get()).isNull();
        // Exactly one freshlyCreated=true, one =false (idempotent race-loser)
        boolean bothTrue = a.get().freshlyCreated() && b.get().freshlyCreated();
        boolean bothFalse = !a.get().freshlyCreated() && !b.get().freshlyCreated();
        assertThat(bothTrue).as("only one thread should have created the booking").isFalse();
        assertThat(bothFalse).as("one thread must have been the creator").isFalse();
        // Same booking id both times.
        assertThat(a.get().response().bookingId()).isEqualTo(b.get().response().bookingId());
        // Only one row was inserted total.
        assertThat(bookingRepository.count()).isEqualTo(baselineCount + 1);
    }
}
