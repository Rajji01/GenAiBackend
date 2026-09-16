package com.ticketing.inventory.repository;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

// @AutoConfigureTestDatabase(replace = NONE) is not optional here — by
// default @DataJpaTest silently swaps in an embedded H2 database, which
// would defeat the entire point: this test exists to prove behaviour
// (unique constraint, @Version) against the exact Postgres version the
// app actually runs on, not against a different database that merely
// speaks similar SQL.
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Testcontainers
class SeatRepositoryTest {

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine")
            .withDatabaseName("inventory")
            .withUsername("inventory_user")
            .withPassword("inventory_pass");

    @DynamicPropertySource
    static void registerProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
    }

    @Autowired
    private SeatRepository seatRepository;

    @Test
    void findByShowId_returnsOnlySeatsForThatShow() {
        seatRepository.save(new Seat(1L, "A1"));
        seatRepository.save(new Seat(1L, "A2"));
        seatRepository.save(new Seat(2L, "A1")); // same seat number, different show — must not collide

        List<Seat> show1Seats = seatRepository.findByShowId(1L);

        assertThat(show1Seats).hasSize(2);
        assertThat(show1Seats).extracting(Seat::getSeatNumber).containsExactlyInAnyOrder("A1", "A2");
    }

    @Test
    void findByShowId_returnsEmptyListForAnUnknownShow() {
        assertThat(seatRepository.findByShowId(999L)).isEmpty();
    }

    @Test
    void newSeat_defaultsToAvailableWithVersionAssignedOnSave() {
        Seat saved = seatRepository.saveAndFlush(new Seat(3L, "B1"));

        assertThat(saved.getStatus()).isEqualTo(SeatStatus.AVAILABLE);
        assertThat(saved.getVersion()).isNotNull(); // Hibernate assigns version 0 on first insert
    }

    @Test
    void duplicateSeatNumberForTheSameShow_violatesTheUniqueConstraint() {
        seatRepository.saveAndFlush(new Seat(4L, "C1"));

        assertThrows(
                org.springframework.dao.DataIntegrityViolationException.class,
                () -> seatRepository.saveAndFlush(new Seat(4L, "C1"))
        );
    }

    // A same-transaction, same-persistence-context "two reads then two
    // writes" test was deliberately NOT written here to prove optimistic
    // locking: within one JPA persistence context, findById() twice for the
    // same id returns the exact same managed instance (first-level cache),
    // so there's no staleness to reproduce without either detaching entities
    // mid-test (which then collides with merge() semantics) or real
    // concurrent threads. That's exactly what Day 5's failure experiment
    // does properly, against the running app, not a same-JVM trick — see
    // the README's hold/release flow and the Day 5 test once it exists.
}
