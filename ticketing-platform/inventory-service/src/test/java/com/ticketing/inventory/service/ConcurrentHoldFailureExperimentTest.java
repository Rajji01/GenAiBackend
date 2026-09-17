package com.ticketing.inventory.service;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;
import com.ticketing.inventory.exception.ConflictException;
import com.ticketing.inventory.repository.SeatRepository;
import com.redis.testcontainers.RedisContainer;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.assertThat;

// Day 5's failure experiment, made repeatable: real threads, real
// Postgres, real Redis — not a sequential simulation of concurrency.
// Every earlier test (HoldServiceTest, SeatRepositoryTest) called things
// one at a time; this is the one place two callers are made to race for
// real, with a CountDownLatch forcing them to fire at (as close to)
// the same instant as the JVM allows.
@SpringBootTest
@ActiveProfiles("test")
@Testcontainers
class ConcurrentHoldFailureExperimentTest {

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
    }

    @Autowired
    private HoldService holdService;

    @Autowired
    private SeatRepository seatRepository;

    /**
     * The end-to-end proof: two callers hit the real {@code hold()} flow
     * for the same seat at the same instant. Redis's SETNX is atomic and
     * single-threaded server-side, so in practice it — not the Postgres
     * @Version check below — is what resolves this race: one caller's
     * SETNX wins, the other's fails immediately and gets a clean
     * ConflictException before Postgres is even touched.
     */
    @Test
    void twoConcurrentHoldsOnTheSameSeat_exactlyOneWins_theOtherGetsACleanConflict() throws Exception {
        Long showId = System.nanoTime();
        Seat seat = seatRepository.saveAndFlush(new Seat(showId, "RACE-1"));
        Long seatId = seat.getId();

        CountDownLatch bothReady = new CountDownLatch(2);
        CountDownLatch go = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(2);

        Callable<String> attemptAsUserA = () -> {
            bothReady.countDown();
            go.await();
            try {
                holdService.hold(showId, seatId, "user-A");
                return "WON";
            } catch (ConflictException e) {
                return "LOST:" + e.getMessage();
            }
        };
        Callable<String> attemptAsUserB = () -> {
            bothReady.countDown();
            go.await();
            try {
                holdService.hold(showId, seatId, "user-B");
                return "WON";
            } catch (ConflictException e) {
                return "LOST:" + e.getMessage();
            }
        };

        Future<String> userA = pool.submit(attemptAsUserA);
        Future<String> userB = pool.submit(attemptAsUserB);

        bothReady.await(2, TimeUnit.SECONDS);
        go.countDown();

        String resultA = userA.get(5, TimeUnit.SECONDS);
        String resultB = userB.get(5, TimeUnit.SECONDS);
        pool.shutdown();

        long wins = java.util.stream.Stream.of(resultA, resultB).filter(r -> r.equals("WON")).count();
        long losses = java.util.stream.Stream.of(resultA, resultB).filter(r -> r.startsWith("LOST")).count();

        assertThat(wins).isEqualTo(1);
        assertThat(losses).isEqualTo(1);
        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.HELD);
    }

    /**
     * The layer-isolated proof: bypass HoldService and Redis entirely and
     * race two threads directly against Postgres's optimistic lock, the
     * mechanism the whole @Version design is actually about. This is
     * what Day 2 explicitly deferred — it needs real concurrent threads,
     * not two sequential reads inside one persistence context.
     */
    @Test
    void twoConcurrentPostgresWritesOnTheSameSeat_exactlyOneSucceeds_viaVersionAlone() throws Exception {
        Long showId = System.nanoTime();
        Seat seat = seatRepository.saveAndFlush(new Seat(showId, "RACE-2"));
        Long seatId = seat.getId();

        CountDownLatch bothReady = new CountDownLatch(2);
        CountDownLatch go = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(2);

        Callable<Boolean> attemptDirectUpdate = () -> {
            bothReady.countDown();
            go.await();
            try {
                Seat s = seatRepository.findById(seatId).orElseThrow();
                s.setStatus(SeatStatus.HELD);
                seatRepository.saveAndFlush(s);
                return true;
            } catch (OptimisticLockingFailureException e) {
                return false;
            }
        };

        Future<Boolean> t1 = pool.submit(attemptDirectUpdate);
        Future<Boolean> t2 = pool.submit(attemptDirectUpdate);

        bothReady.await(2, TimeUnit.SECONDS);
        go.countDown();

        boolean r1 = t1.get(5, TimeUnit.SECONDS);
        boolean r2 = t2.get(5, TimeUnit.SECONDS);
        pool.shutdown();

        assertThat(r1 ^ r2).as("exactly one of the two direct writes must win").isTrue();
        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.HELD);
    }
}
