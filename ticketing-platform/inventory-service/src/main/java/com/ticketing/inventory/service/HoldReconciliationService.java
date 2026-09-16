package com.ticketing.inventory.service;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;
import com.ticketing.inventory.repository.SeatRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

// Closes the gap the README's Day 1 design flagged as open: when a hold's
// Redis key expires on its own TTL (the common case — a client abandons
// the flow, nobody calls /release), nothing else was watching, so the
// Postgres seat would stay HELD forever. That fails the Week 1 DoD line
// "Redis TTL hold expires correctly (verify after TTL, seat free)" —
// the *seat* has to become available again, not just the Redis key.
//
// Polling, not Redis keyspace-notification pub/sub, on purpose: pub/sub
// delivery isn't guaranteed (a notification fired while the app was
// restarting is simply lost), which would leave a seat stuck HELD with no
// second chance to recover. A periodic sweep is self-healing even after a
// missed event, at the cost of a bounded staleness window between a TTL
// expiring and the next sweep — an explicit, acceptable trade-off here.
// Gated behind a property (default on) rather than always-on: this is
// what lets test classes that don't care about reconciliation disable it
// wholesale via src/test/resources/application.yml, instead of every
// @SpringBootTest in the suite racing a live background scheduler against
// Testcontainers that may already be torn down by the time it fires
// (a real failure this project hit — see HoldReconciliationServiceTest
// for the one test class that explicitly re-enables it).
@Service
@ConditionalOnProperty(prefix = "inventory.reconciliation", name = "enabled", havingValue = "true", matchIfMissing = true)
@RequiredArgsConstructor
public class HoldReconciliationService {

    private static final Logger log = LoggerFactory.getLogger(HoldReconciliationService.class);

    private final SeatRepository seatRepository;
    private final StringRedisTemplate redisTemplate;

    @Scheduled(fixedDelayString = "${inventory.reconciliation.interval-ms:30000}")
    public void reconcileExpiredHolds() {
        int freed = reconcileOnce();
        if (freed > 0) {
            log.info("reconciliation_freed_seats count={}", freed);
        }
    }

    // Split out from the @Scheduled method so tests can trigger exactly
    // one pass deterministically instead of waiting on a timer.
    @Transactional
    public int reconcileOnce() {
        int freedCount = 0;
        for (Seat seat : seatRepository.findByStatus(SeatStatus.HELD)) {
            String key = "hold:" + seat.getId();
            if (Boolean.FALSE.equals(redisTemplate.hasKey(key))) {
                seat.setStatus(SeatStatus.AVAILABLE);
                seatRepository.save(seat);
                freedCount++;
                log.info("reconciliation_freed_seat seatId={}", seat.getId());
            }
        }
        return freedCount;
    }
}
