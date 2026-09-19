package com.ticketing.booking.repository;

import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingStatus;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

// @DataJpaTest + real Postgres (NOT H2). replace = NONE stops Spring Boot
// from silently swapping in an embedded H2 — the entire point of Day 2's
// idempotency guarantee is the UNIQUE constraint on idempotency_key, and
// H2's dialect could hide a bug in exactly how Postgres reports the
// violation. Same discipline as inventory-service.
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Testcontainers
class BookingRepositoryTest {

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
    private BookingRepository bookingRepository;

    @Test
    void savingABooking_assignsAnIdAVersionAndACreatedAt() {
        Booking saved = bookingRepository.saveAndFlush(
                new Booking("key-1", "hash-1", 1L, "user-1"));

        assertThat(saved.getId()).isNotNull();
        assertThat(saved.getVersion()).isNotNull();
        assertThat(saved.getCreatedAt()).isNotNull();
        assertThat(saved.getStatus()).isEqualTo(BookingStatus.PENDING);
    }

    @Test
    void findByIdempotencyKey_returnsTheBookingWhenPresent() {
        bookingRepository.saveAndFlush(new Booking("key-lookup", "h", 1L, "user-1"));

        assertThat(bookingRepository.findByIdempotencyKey("key-lookup")).isPresent();
        assertThat(bookingRepository.findByIdempotencyKey("no-such-key")).isEmpty();
    }

    // The DB-side half of the idempotency guarantee: two rows with the same
    // idempotency_key must be impossible, no matter how the service layer
    // races (see BookingService's DataIntegrityViolationException recovery).
    @Test
    void twoRowsWithTheSameIdempotencyKey_areRejectedByTheUniqueIndex() {
        bookingRepository.saveAndFlush(new Booking("dup-key", "h1", 1L, "user-1"));

        assertThrows(DataIntegrityViolationException.class, () ->
                bookingRepository.saveAndFlush(new Booking("dup-key", "h2", 1L, "user-2")));
    }
}
