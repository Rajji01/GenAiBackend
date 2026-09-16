package com.ticketing.inventory.service;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;
import com.ticketing.inventory.repository.SeatRepository;
import com.redis.testcontainers.RedisContainer;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@Testcontainers
class HoldReconciliationServiceTest {

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine")
            .withDatabaseName("inventory")
            .withUsername("inventory_user")
            .withPassword("inventory_pass");

    @Container
    static RedisContainer redis = new RedisContainer("redis:7-alpine");

    @DynamicPropertySource
    static void registerProperties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", postgres::getJdbcUrl);
        registry.add("spring.datasource.username", postgres::getUsername);
        registry.add("spring.datasource.password", postgres::getPassword);
        registry.add("spring.data.redis.host", redis::getHost);
        registry.add("spring.data.redis.port", () -> redis.getMappedPort(6379));
        // src/test/resources/application.yml disables reconciliation for
        // the whole suite by default (see its comment) — this is the one
        // test class that needs the bean to actually exist. The interval
        // is set far longer than any test here runs, so every assertion
        // is against an explicit reconcileOnce() call, never a race with
        // the background @Scheduled timer.
        registry.add("inventory.reconciliation.enabled", () -> "true");
        registry.add("inventory.reconciliation.interval-ms", () -> "3600000");
    }

    @Autowired
    private HoldReconciliationService reconciliationService;

    @Autowired
    private SeatRepository seatRepository;

    @Autowired
    private StringRedisTemplate redisTemplate;

    @Test
    void reconcileOnce_freesAHeldSeatWhoseRedisKeyHasAlreadyExpired() {
        Seat seat = new Seat(System.nanoTime(), "A1");
        seat.setStatus(SeatStatus.HELD);
        seat = seatRepository.saveAndFlush(seat);
        // Deliberately no "hold:{id}" key written — simulates the TTL
        // having already expired with nobody watching.

        int freed = reconciliationService.reconcileOnce();

        assertThat(freed).isEqualTo(1);
        assertThat(seatRepository.findById(seat.getId()).orElseThrow().getStatus())
                .isEqualTo(SeatStatus.AVAILABLE);
    }

    @Test
    void reconcileOnce_leavesAHeldSeatAlone_ifItsHoldKeyIsStillActive() {
        Seat seat = new Seat(System.nanoTime(), "A1");
        seat.setStatus(SeatStatus.HELD);
        seat = seatRepository.saveAndFlush(seat);
        redisTemplate.opsForValue().set("hold:" + seat.getId(), "user-1", Duration.ofMinutes(5));

        int freed = reconciliationService.reconcileOnce();

        assertThat(freed).isEqualTo(0);
        assertThat(seatRepository.findById(seat.getId()).orElseThrow().getStatus())
                .isEqualTo(SeatStatus.HELD);
    }

    @Test
    void reconcileOnce_ignoresAvailableAndBookedSeats_regardlessOfRedis() {
        Seat available = seatRepository.saveAndFlush(new Seat(System.nanoTime(), "A1"));
        Seat booked = new Seat(System.nanoTime(), "A1");
        booked.setStatus(SeatStatus.BOOKED);
        booked = seatRepository.saveAndFlush(booked);

        int freed = reconciliationService.reconcileOnce();

        assertThat(freed).isEqualTo(0);
        assertThat(seatRepository.findById(available.getId()).orElseThrow().getStatus())
                .isEqualTo(SeatStatus.AVAILABLE);
        assertThat(seatRepository.findById(booked.getId()).orElseThrow().getStatus())
                .isEqualTo(SeatStatus.BOOKED);
    }
}
