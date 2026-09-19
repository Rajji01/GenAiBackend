package com.ticketing.booking.service;

import com.ticketing.booking.client.InventoryClient;
import com.ticketing.booking.client.InventoryClientException;
import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingSeat;
import com.ticketing.booking.entity.BookingStatus;
import com.ticketing.booking.repository.BookingRepository;
import com.ticketing.booking.repository.BookingSeatRepository;
import com.ticketing.booking.service.BookingSagaService.SagaFailedException;
import com.ticketing.booking.service.PaymentStub.PaymentFailedException;
import com.ticketing.booking.service.PaymentStub.PaymentResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

// End-to-end saga behavior against real Postgres, with the outgoing
// integrations (inventory + payment) mocked. Mocking at the HTTP boundary
// keeps these tests deterministic — no other service needed — while still
// exercising the real state-machine writes and compensation paths.
//
// The mocked BOUNDARIES are: InventoryClient (all three methods) and
// PaymentStub. Everything the saga does with the DB is real.
@SpringBootTest
@Testcontainers
class BookingSagaServiceTest {

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

    @MockBean
    private InventoryClient inventoryClient;

    @MockBean
    private PaymentStub paymentStub;

    @Autowired
    private BookingSagaService sagaService;

    @Autowired
    private BookingRepository bookingRepository;

    @Autowired
    private BookingSeatRepository bookingSeatRepository;

    private Long showId;
    private String holderId;
    private List<Long> seatIds;
    private Long bookingId;

    @BeforeEach
    void seedPendingBooking() {
        showId = System.nanoTime();
        holderId = "user-" + UUID.randomUUID();
        seatIds = List.of(5L, 6L);

        Booking pending = bookingRepository.saveAndFlush(new Booking(
                UUID.randomUUID().toString(), "hash-x", showId, holderId));
        bookingId = pending.getId();
        for (Long s : seatIds) {
            bookingSeatRepository.saveAndFlush(new BookingSeat(bookingId, s));
        }
    }

    @Test
    void happyPath_movesPendingThroughToConfirmed_andStampsPaymentRefAndHoldTokens() {
        when(inventoryClient.hold(eq(showId), anyLong(), eq(holderId)))
                .thenAnswer(inv -> new InventoryClient.HoldResponse(inv.getArgument(1), holderId, 300));
        when(paymentStub.charge(eq(bookingId), eq(holderId)))
                .thenReturn(new PaymentResult("pay-ok-1"));
        when(inventoryClient.confirm(eq(showId), anyLong(), eq(holderId)))
                .thenAnswer(inv -> new InventoryClient.ConfirmResponse(inv.getArgument(1), holderId, "BOOKED"));

        Booking finalState = sagaService.runSaga(bookingId, showId, holderId, seatIds);

        assertThat(finalState.getStatus()).isEqualTo(BookingStatus.CONFIRMED);
        assertThat(finalState.getPaymentRef()).isEqualTo("pay-ok-1");
        assertThat(finalState.getConfirmedAt()).isNotNull();

        // Every hold token was recorded on the bridge rows.
        List<BookingSeat> bridges = bookingSeatRepository.findByBookingId(bookingId);
        assertThat(bridges).allSatisfy(bs -> assertThat(bs.getHoldToken()).isEqualTo(holderId));
        assertThat(bridges).allSatisfy(bs -> assertThat(bs.getReleasedAt()).isNull());
    }

    @Test
    void inventoryHoldConflict_onTheFirstSeat_leavesBookingFailedAndTouchesNothingElse() {
        when(inventoryClient.hold(eq(showId), eq(5L), eq(holderId)))
                .thenThrow(new InventoryClientException(409, "seat 5 already held"));

        SagaFailedException failure = assertThrows(SagaFailedException.class,
                () -> sagaService.runSaga(bookingId, showId, holderId, seatIds));

        assertThat(failure.getBookingId()).isEqualTo(bookingId);
        assertThat(bookingRepository.findById(bookingId).orElseThrow().getStatus())
                .isEqualTo(BookingStatus.FAILED);
        // Nothing was held → nothing to release → payment never called.
        verifyNoInteractions(paymentStub);
        verify(inventoryClient, times(0)).release(anyLong(), anyLong(), anyString());
    }

    @Test
    void inventoryHoldConflict_onTheSecondSeat_releasesTheFirstOneAsCompensation() {
        when(inventoryClient.hold(eq(showId), eq(5L), eq(holderId)))
                .thenReturn(new InventoryClient.HoldResponse(5L, holderId, 300));
        when(inventoryClient.hold(eq(showId), eq(6L), eq(holderId)))
                .thenThrow(new InventoryClientException(409, "seat 6 already held"));

        SagaFailedException failure = assertThrows(SagaFailedException.class,
                () -> sagaService.runSaga(bookingId, showId, holderId, seatIds));

        assertThat(failure.getBookingId()).isEqualTo(bookingId);
        assertThat(bookingRepository.findById(bookingId).orElseThrow().getStatus())
                .isEqualTo(BookingStatus.FAILED);
        // The one seat we DID hold has to be released; the one that conflicted must NOT be.
        verify(inventoryClient, times(1)).release(eq(showId), eq(5L), eq(holderId));
        verify(inventoryClient, times(0)).release(eq(showId), eq(6L), eq(holderId));
        // Bridge row for the released seat gets a released_at stamp; the other stays null.
        List<BookingSeat> bridges = bookingSeatRepository.findByBookingId(bookingId);
        BookingSeat five = bridges.stream().filter(b -> b.getSeatId().equals(5L)).findFirst().orElseThrow();
        BookingSeat six = bridges.stream().filter(b -> b.getSeatId().equals(6L)).findFirst().orElseThrow();
        assertThat(five.getReleasedAt()).isNotNull();
        assertThat(six.getReleasedAt()).isNull();
        // Payment was never called.
        verifyNoInteractions(paymentStub);
    }

    @Test
    void paymentFailure_afterAllHolds_releasesAllHeldSeats_andMarksFailed() {
        when(inventoryClient.hold(eq(showId), anyLong(), eq(holderId)))
                .thenAnswer(inv -> new InventoryClient.HoldResponse(inv.getArgument(1), holderId, 300));
        when(paymentStub.charge(eq(bookingId), eq(holderId)))
                .thenThrow(new PaymentFailedException("gateway 500"));

        SagaFailedException failure = assertThrows(SagaFailedException.class,
                () -> sagaService.runSaga(bookingId, showId, holderId, seatIds));

        assertThat(failure.getMessage()).contains("payment failed");
        assertThat(bookingRepository.findById(bookingId).orElseThrow().getStatus())
                .isEqualTo(BookingStatus.FAILED);
        // Every held seat got a release call.
        verify(inventoryClient, times(1)).release(eq(showId), eq(5L), eq(holderId));
        verify(inventoryClient, times(1)).release(eq(showId), eq(6L), eq(holderId));
        // Confirm never called on any seat.
        verify(inventoryClient, times(0)).confirm(anyLong(), anyLong(), anyString());
    }

    @Test
    void releaseFailureDuringCompensation_isSwallowed_bookingStillMarkedFailed() {
        // The tricky honest case: compensation itself fails. Booking should
        // still end in FAILED — hold TTL + inventory-service's own
        // reconciliation is the safety net (Week 1 guarantee).
        when(inventoryClient.hold(eq(showId), anyLong(), eq(holderId)))
                .thenAnswer(inv -> new InventoryClient.HoldResponse(inv.getArgument(1), holderId, 300));
        when(paymentStub.charge(anyLong(), anyString()))
                .thenThrow(new PaymentFailedException("gateway 500"));
        doThrow(new InventoryClientException(0, "inventory down"))
                .when(inventoryClient).release(anyLong(), anyLong(), anyString());

        assertThrows(SagaFailedException.class,
                () -> sagaService.runSaga(bookingId, showId, holderId, seatIds));

        assertThat(bookingRepository.findById(bookingId).orElseThrow().getStatus())
                .isEqualTo(BookingStatus.FAILED);
    }
}
