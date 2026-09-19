package com.ticketing.inventory.service;

import com.ticketing.inventory.dto.HoldResponse;
import com.ticketing.inventory.dto.ConfirmResponse;
import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;
import com.ticketing.inventory.exception.ConflictException;
import com.ticketing.inventory.exception.ForbiddenException;
import com.ticketing.inventory.exception.ResourceNotFoundException;
import com.ticketing.inventory.repository.SeatRepository;
import com.redis.testcontainers.RedisContainer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

// Needs BOTH real stores at once, deliberately — this is exactly the layer
// where a fake of either one would hide the coordination bug this class
// exists to avoid (Redis lock outliving Postgres state, or vice versa).
//
// "test" profile disables HoldReconciliationService's background sweep —
// these tests assert on HELD seats mid-test, and a live scheduler racing
// in every 30s has no business touching state a test is still inspecting.
@SpringBootTest
@ActiveProfiles("test")
@Testcontainers
class HoldServiceTest {

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

    @Autowired
    private StringRedisTemplate redisTemplate;

    @Autowired
    private PlatformTransactionManager txManager;

    private Long showId;
    private Long seatId;

    @BeforeEach
    void seedOneAvailableSeat() {
        showId = System.nanoTime(); // unique per test, no cross-test collisions
        Seat seat = seatRepository.saveAndFlush(new Seat(showId, "A1"));
        seatId = seat.getId();
    }

    @Test
    void hold_grantsTheHold_andFlipsTheSeatToHeldInPostgres() {
        HoldResponse response = holdService.hold(showId, seatId, "user-1");

        assertThat(response.seatId()).isEqualTo(seatId);
        assertThat(response.holderId()).isEqualTo("user-1");
        assertThat(response.ttlSeconds()).isGreaterThan(0);

        Seat reloaded = seatRepository.findById(seatId).orElseThrow();
        assertThat(reloaded.getStatus()).isEqualTo(SeatStatus.HELD);
        assertThat(redisTemplate.opsForValue().get("hold:" + seatId)).isEqualTo("user-1");
    }

    @Test
    void hold_bySameHolderTwice_isIdempotent_notASecondHoldOrAnError() {
        holdService.hold(showId, seatId, "user-1");
        HoldResponse retry = holdService.hold(showId, seatId, "user-1");

        assertThat(retry.holderId()).isEqualTo("user-1");
        // Still exactly one HELD seat, not double-transitioned or errored.
        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.HELD);
    }

    @Test
    void hold_byADifferentHolder_whileAlreadyHeld_isAConflict() {
        holdService.hold(showId, seatId, "user-1");

        ConflictException ex = assertThrows(ConflictException.class,
                () -> holdService.hold(showId, seatId, "user-2"));
        assertThat(ex.getMessage()).contains("already held");

        // The original holder's grant must be untouched by the rejected attempt.
        assertThat(redisTemplate.opsForValue().get("hold:" + seatId)).isEqualTo("user-1");
    }

    @Test
    void hold_onASeatThatIsAlreadyBooked_isAConflict_andReleasesTheRedisKeyItJustTook() {
        Seat seat = seatRepository.findById(seatId).orElseThrow();
        seat.setStatus(SeatStatus.BOOKED);
        seatRepository.saveAndFlush(seat);

        assertThrows(ConflictException.class, () -> holdService.hold(showId, seatId, "user-1"));

        // The Redis key HoldService acquired before discovering the
        // Postgres conflict must not be left dangling for 5 minutes.
        assertThat(redisTemplate.opsForValue().get("hold:" + seatId)).isNull();
    }

    @Test
    void hold_onASeatBelongingToADifferentShow_is404() {
        assertThrows(ResourceNotFoundException.class,
                () -> holdService.hold(showId + 1, seatId, "user-1"));
    }

    @Test
    void hold_onAnUnknownSeat_is404() {
        assertThrows(ResourceNotFoundException.class,
                () -> holdService.hold(showId, -1L, "user-1"));
    }

    @Test
    void release_byTheRightfulHolder_freesTheSeatAndTheRedisKey() {
        holdService.hold(showId, seatId, "user-1");

        holdService.release(showId, seatId, "user-1");

        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.AVAILABLE);
        assertThat(redisTemplate.opsForValue().get("hold:" + seatId)).isNull();
    }

    @Test
    void release_byTheWrongHolder_isForbidden_andLeavesTheHoldIntact() {
        holdService.hold(showId, seatId, "user-1");

        assertThrows(ForbiddenException.class, () -> holdService.release(showId, seatId, "user-2"));

        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.HELD);
        assertThat(redisTemplate.opsForValue().get("hold:" + seatId)).isEqualTo("user-1");
    }

    @Test
    void release_whenNothingIsHeld_isANoop_notAnError() {
        // No exception expected — same TTL-expired-already scenario, and
        // release is idempotent by design.
        holdService.release(showId, seatId, "user-1");

        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.AVAILABLE);
    }

    @Test
    void release_doesNotUnbookAConfirmedBooking() {
        holdService.hold(showId, seatId, "user-1");
        Seat seat = seatRepository.findById(seatId).orElseThrow();
        seat.setStatus(SeatStatus.BOOKED); // simulates a booking confirmation landing while held
        seatRepository.saveAndFlush(seat);

        holdService.release(showId, seatId, "user-1");

        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.BOOKED);
    }

    @Test
    void confirm_byHoldOwner_booksTheSeat_andRemovesTheTemporaryRedisKey() {
        holdService.hold(showId, seatId, "user-1");

        ConfirmResponse response = holdService.confirm(showId, seatId, "user-1");

        assertThat(response.status()).isEqualTo("BOOKED");
        Seat booked = seatRepository.findById(seatId).orElseThrow();
        assertThat(booked.getStatus()).isEqualTo(SeatStatus.BOOKED);
        assertThat(booked.getBookedByHolderId()).isEqualTo("user-1");
        assertThat(redisTemplate.opsForValue().get("hold:" + seatId)).isNull();
    }

    @Test
    void confirm_bySameHolderTwice_isIdempotent() {
        holdService.hold(showId, seatId, "user-1");
        holdService.confirm(showId, seatId, "user-1");

        ConfirmResponse retry = holdService.confirm(showId, seatId, "user-1");

        assertThat(retry.status()).isEqualTo("BOOKED");
    }

    @Test
    void confirm_byAnotherHolder_isForbidden_andLeavesTheHoldIntact() {
        holdService.hold(showId, seatId, "user-1");

        assertThrows(ForbiddenException.class, () -> holdService.confirm(showId, seatId, "user-2"));

        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.HELD);
        assertThat(redisTemplate.opsForValue().get("hold:" + seatId)).isEqualTo("user-1");
    }

    @Test
    void confirm_withoutALiveHold_isAConflict() {
        assertThrows(ConflictException.class, () -> holdService.confirm(showId, seatId, "user-1"));
    }

    // The window between a Redis TTL expiring and the next reconciliation
    // sweep: Postgres still says HELD, but the hold is already gone. A late
    // payment callback must not book a seat whose hold no longer exists.
    @Test
    void confirm_afterTheRedisHoldExpired_butBeforeReconciliation_isAConflict() {
        holdService.hold(showId, seatId, "user-1");
        redisTemplate.delete("hold:" + seatId); // simulate the TTL expiring

        assertThrows(ConflictException.class, () -> holdService.confirm(showId, seatId, "user-1"));

        Seat seat = seatRepository.findById(seatId).orElseThrow();
        assertThat(seat.getStatus()).isEqualTo(SeatStatus.HELD);
        assertThat(seat.getBookedByHolderId()).isNull();
    }

    @Test
    void confirm_onASeatBookedBySomeoneElse_isAConflict_andKeepsTheOriginalOwner() {
        holdService.hold(showId, seatId, "user-1");
        holdService.confirm(showId, seatId, "user-1");

        assertThrows(ConflictException.class, () -> holdService.confirm(showId, seatId, "user-2"));

        assertThat(seatRepository.findById(seatId).orElseThrow().getBookedByHolderId()).isEqualTo("user-1");
    }

    // Proves the afterCommit fix in HoldService.confirm(): if the surrounding
    // transaction ends up rolling back, the Redis hold key must survive so a
    // retry by the same holder can still succeed. An eager pre-commit delete
    // would leave the seat rolled back to HELD with the key already gone,
    // letting reconciliation silently free a seat someone had paid for.
    @Test
    void confirm_whenTheOuterTransactionRollsBack_leavesTheRedisHoldIntact() {
        holdService.hold(showId, seatId, "user-1");
        String key = "hold:" + seatId;
        assertThat(redisTemplate.opsForValue().get(key)).isEqualTo("user-1");

        TransactionTemplate tx = new TransactionTemplate(txManager);
        tx.executeWithoutResult(status -> {
            holdService.confirm(showId, seatId, "user-1"); // joins the outer tx
            status.setRollbackOnly();                       // force a rollback
        });

        // Postgres rolled back → still HELD, no bookedByHolderId set.
        Seat seat = seatRepository.findById(seatId).orElseThrow();
        assertThat(seat.getStatus()).isEqualTo(SeatStatus.HELD);
        assertThat(seat.getBookedByHolderId()).isNull();

        // afterCommit never fired → key is still there, retry can succeed.
        assertThat(redisTemplate.opsForValue().get(key)).isEqualTo("user-1");

        ConfirmResponse retry = holdService.confirm(showId, seatId, "user-1");
        assertThat(retry.status()).isEqualTo("BOOKED");
        assertThat(seatRepository.findById(seatId).orElseThrow().getStatus()).isEqualTo(SeatStatus.BOOKED);
        assertThat(redisTemplate.opsForValue().get(key)).isNull(); // this time it did commit
    }
}
