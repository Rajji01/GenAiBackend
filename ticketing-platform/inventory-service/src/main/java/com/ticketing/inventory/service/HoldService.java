package com.ticketing.inventory.service;

import com.ticketing.inventory.config.InventoryProperties;
import com.ticketing.inventory.dto.HoldResponse;
import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;
import com.ticketing.inventory.exception.ConflictException;
import com.ticketing.inventory.exception.ForbiddenException;
import com.ticketing.inventory.exception.ResourceNotFoundException;
import com.ticketing.inventory.repository.SeatRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;

// The concurrency heart of the whole platform. Two stores, two jobs:
//   - Redis SETNX is the fast, TTL-backed mutual-exclusion check — it's
//     what makes an abandoned hold self-heal after a configurable TTL
//     (`inventory.hold.ttl-seconds`, 5 minutes by default) with no
//     cleanup job.
//   - Postgres's @Version optimistic lock is the actual correctness
//     guarantee — even if the Redis check somehow raced or the key
//     expired mid-request, two concurrent UPDATEs against the same seat
//     row cannot both succeed.
// Redis alone would be enough to prevent two holds from being *granted*,
// but it can't protect the Postgres row from a completely unrelated write
// path (a future booking-service call, a manual admin fix) — that's what
// @Version is for. Neither store is trusted alone.
@Service
@RequiredArgsConstructor
public class HoldService {

    private static final Logger log = LoggerFactory.getLogger(HoldService.class);

    private final StringRedisTemplate redisTemplate;
    private final SeatRepository seatRepository;
    private final InventoryProperties properties;

    @Transactional
    public HoldResponse hold(Long showId, Long seatId, String holderId) {
        String key = holdKey(seatId);

        Boolean acquired = redisTemplate.opsForValue().setIfAbsent(key, holderId, holdTtl());
        if (Boolean.TRUE.equals(acquired)) {
            return grantHold(showId, seatId, holderId, key);
        }

        // Someone already holds the Redis key. If it's the same holder
        // asking again (e.g. a client retry after a dropped response),
        // that's not a conflict — the LLD requirement this satisfies:
        // retrying a hold must never create a second hold or error out.
        String existingHolder = redisTemplate.opsForValue().get(key);
        if (holderId.equals(existingHolder)) {
            log.info("hold_idempotent_retry seatId={} holderId={}", seatId, holderId);
            Long ttl = redisTemplate.getExpire(key);
            return new HoldResponse(seatId, holderId, ttl == null ? 0 : ttl);
        }

        log.info("hold_conflict seatId={} requestedBy={}", seatId, holderId);
        throw new ConflictException("Seat " + seatId + " is already held by someone else");
    }

    private HoldResponse grantHold(Long showId, Long seatId, String holderId, String redisKey) {
        try {
            Seat seat = seatRepository.findById(seatId)
                    .orElseThrow(() -> new ResourceNotFoundException("Seat not found: " + seatId));

            if (!seat.getShowId().equals(showId)) {
                // The seat exists, just not under this show — from this
                // URL's point of view it doesn't exist, same as backend's
                // ResourceNotFoundException usage elsewhere.
                throw new ResourceNotFoundException("Seat " + seatId + " not found for show " + showId);
            }

            if (seat.getStatus() != SeatStatus.AVAILABLE) {
                throw new ConflictException("Seat " + seatId + " is not available (status=" + seat.getStatus() + ")");
            }

            seat.setStatus(SeatStatus.HELD);
            seatRepository.save(seat); // may throw OptimisticLockingFailureException

            log.info("hold_granted seatId={} holderId={}", seatId, holderId);
            return new HoldResponse(seatId, holderId, properties.hold().ttlSeconds());
        } catch (RuntimeException ex) {
            // We already own the Redis key at this point — if anything
            // past that fails, the Redis lock must not outlive the
            // Postgres state it was supposed to protect. Otherwise the
            // seat would look "held" in Redis for up to 5 minutes with no
            // actual hold behind it.
            redisTemplate.delete(redisKey);
            throw ex;
        }
    }

    @Transactional
    public void release(Long showId, Long seatId, String holderId) {
        String key = holdKey(seatId);
        String existingHolder = redisTemplate.opsForValue().get(key);

        if (existingHolder == null) {
            // Already released, or the TTL beat us to it. From the
            // caller's point of view the end state (no hold) is achieved
            // either way — release is idempotent by design, not an error.
            log.info("release_noop_already_unheld seatId={}", seatId);
            return;
        }

        if (!existingHolder.equals(holderId)) {
            log.info("release_forbidden seatId={} requestedBy={}", seatId, holderId);
            throw new ForbiddenException("holderId does not own the hold on seat " + seatId);
        }

        redisTemplate.delete(key);

        Seat seat = seatRepository.findById(seatId)
                .orElseThrow(() -> new ResourceNotFoundException("Seat not found: " + seatId));
        if (!seat.getShowId().equals(showId)) {
            throw new ResourceNotFoundException("Seat " + seatId + " not found for show " + showId);
        }

        // Only revert HELD -> AVAILABLE. If the seat is already BOOKED (a
        // confirmed booking landed while this hold was active), releasing
        // the hold must not un-book it — a hold and a confirmed booking
        // are different lifecycle stages, and this is the guard that keeps
        // them from being conflated.
        if (seat.getStatus() == SeatStatus.HELD) {
            seat.setStatus(SeatStatus.AVAILABLE);
            seatRepository.save(seat);
        }

        log.info("release_granted seatId={} holderId={}", seatId, holderId);
    }

    private String holdKey(Long seatId) {
        return "hold:" + seatId;
    }

    private Duration holdTtl() {
        return Duration.ofSeconds(properties.hold().ttlSeconds());
    }
}
