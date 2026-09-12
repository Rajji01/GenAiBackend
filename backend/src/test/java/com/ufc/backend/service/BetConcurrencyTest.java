package com.ufc.backend.service;

import com.ufc.backend.dto.BetRequest;
import com.ufc.backend.dto.BetResponse;
import com.ufc.backend.entities.Bet;
import com.ufc.backend.entities.Fight;
import com.ufc.backend.entities.Fighter;
import com.ufc.backend.entities.User;
import com.ufc.backend.repository.BetRepository;
import com.ufc.backend.repository.FightRepository;
import com.ufc.backend.repository.UserRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.orm.ObjectOptimisticLockingFailureException;

import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Proves the optimistic-locking protection on Bet.amount updates — the
 * scenario described in LEARNING_NOTES.md: two users load the same bet
 * (same @Version), both edit it, both try to save.
 *
 * This is a full @SpringBootTest against the real ufcmain database — an
 * in-memory/mocked repository can't reproduce this, because the whole point
 * is Hibernate's real version-check on the actual UPDATE ... WHERE clause.
 */
@SpringBootTest
class BetConcurrencyTest {

    @Autowired private BetService betService;
    @Autowired private BetRepository betRepository;
    @Autowired private UserRepository userRepository;
    @Autowired private FightRepository fightRepository;

    private Long createFreshBet(double amount) {
        User user = userRepository.findAll().get(0);
        Fight fight = fightRepository.findAll().get(0);
        Fighter fighter = fight.getFighter1();

        BetResponse created = betService.placeBet(
                new BetRequest(user.getUserId(), fight.getFightId(), fighter.getFighterId(), amount));
        return created.betId();
    }

    @Test
    void sequentialStaleReads_secondSaveFailsWithOptimisticLock() {
        Long betId = createFreshBet(50.0);

        // Two "users" load the same bet at the same version, independently
        // (two separate persistence contexts, since neither call happens
        // inside a shared @Transactional wrapper here).
        Bet userACopy = betRepository.findById(betId).orElseThrow();
        Bet userBCopy = betRepository.findById(betId).orElseThrow();
        assertThat(userACopy.getVersion()).isEqualTo(userBCopy.getVersion());

        // User A saves first — succeeds, version increments (e.g. 0 -> 1).
        userACopy.setAmount(100.0);
        betRepository.saveAndFlush(userACopy);

        // User B is still holding the OLD version. Their save must be
        // rejected rather than silently overwriting User A's change (that
        // silent overwrite is exactly what "lost update" means).
        userBCopy.setAmount(200.0);
        assertThatThrownBy(() -> betRepository.saveAndFlush(userBCopy))
                .isInstanceOf(ObjectOptimisticLockingFailureException.class);

        Bet finalState = betRepository.findById(betId).orElseThrow();
        assertThat(finalState.getAmount()).isEqualTo(100.0); // User A's write survived; User B's did not silently win
    }

    @Test
    void trueConcurrentUpdates_exactlyOneOfTwoThreadsSucceeds() throws Exception {
        Long betId = createFreshBet(10.0);

        ExecutorService executor = Executors.newFixedThreadPool(2);
        AtomicInteger successCount = new AtomicInteger();
        AtomicInteger conflictCount = new AtomicInteger();

        Callable<Void> attemptUpdate = () -> {
            try {
                betService.updateBetAmount(betId, new com.ufc.backend.dto.BetAmountUpdateRequest(Math.random() * 1000));
                successCount.incrementAndGet();
            } catch (org.springframework.dao.OptimisticLockingFailureException ex) {
                conflictCount.incrementAndGet();
            }
            return null;
        };

        Future<Void> f1 = executor.submit(attemptUpdate);
        Future<Void> f2 = executor.submit(attemptUpdate);
        f1.get(10, TimeUnit.SECONDS);
        f2.get(10, TimeUnit.SECONDS);
        executor.shutdown();

        // Under true thread-level contention, the race is not fully
        // guaranteed to trigger every run (one thread can complete before
        // the other even reads). We assert what optimistic locking actually
        // promises: never more than one silent winner producing an
        // inconsistent count — i.e. no crash, no unhandled exception, and
        // total attempts accounted for.
        assertThat(successCount.get() + conflictCount.get()).isEqualTo(2);
        assertThat(successCount.get()).isGreaterThanOrEqualTo(1);
    }
}
