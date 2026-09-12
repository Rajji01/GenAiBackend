package com.ufc.backend.seed;

import com.ufc.backend.entities.Event;
import com.ufc.backend.entities.Fight;
import com.ufc.backend.entities.Fighter;
import com.ufc.backend.entities.User;
import com.ufc.backend.entities.WeightClass;
import com.ufc.backend.repository.EventRepository;
import com.ufc.backend.repository.FightRepository;
import com.ufc.backend.repository.FighterRepository;
import com.ufc.backend.repository.UserRepository;
import com.ufc.backend.repository.WeightClassRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Configuration;
import org.springframework.transaction.annotation.Transactional;

import java.util.Date;
import java.util.List;

/**
 * Seeds just enough reference data (fighters, an event, a fight, users) to
 * exercise the betting flow end to end. Unlike ProductSeedConfig, this is
 * idempotent — it only inserts anything the first time (checked via
 * fightRepository.count()), so restarting the app doesn't pile up duplicate
 * rows every time.
 */
@Configuration
@RequiredArgsConstructor
public class ReferenceDataSeeder {

    private static final Logger log = LoggerFactory.getLogger(ReferenceDataSeeder.class);

    private final WeightClassRepository weightClassRepository;
    private final FighterRepository fighterRepository;
    private final EventRepository eventRepository;
    private final FightRepository fightRepository;
    private final UserRepository userRepository;

    @org.springframework.context.annotation.Bean
    @Transactional
    CommandLineRunner seedBettingReferenceData() {
        return args -> {
            if (fightRepository.count() > 0) {
                log.info("Reference data already present, skipping seed.");
                return;
            }

            List<WeightClass> weightClasses = weightClassRepository.findAll();
            if (weightClasses.isEmpty()) {
                log.warn("No weight classes found — skipping fight/bet reference data seed.");
                return;
            }
            WeightClass weightClass = weightClasses.get(0);

            Fighter fighter1 = fighterRepository.save(Fighter.builder()
                    .firstName("Alex").lastName("Pereira").nickname("Poatan")
                    .country("Brazil").heightCm(193.0).reachCm(203.0)
                    .weightClass(weightClass).stance(Fighter.Stance.ORTHODOX)
                    .recordWins(12).recordLosses(2).recordDraws(0)
                    .build());

            Fighter fighter2 = fighterRepository.save(Fighter.builder()
                    .firstName("Israel").lastName("Adesanya").nickname("The Last Stylebender")
                    .country("Nigeria").heightCm(193.0).reachCm(203.0)
                    .weightClass(weightClass).stance(Fighter.Stance.SWITCH)
                    .recordWins(24).recordLosses(4).recordDraws(0)
                    .build());

            userRepository.save(User.builder()
                    .username("bettor_one").email("bettor_one@example.com")
                    .passwordHash("dev-only-not-real-hash")
                    .build());
            userRepository.save(User.builder()
                    .username("bettor_two").email("bettor_two@example.com")
                    .passwordHash("dev-only-not-real-hash")
                    .build());

            Event event = eventRepository.save(Event.builder()
                    .eventName("UFC 300").eventDate(new Date()).location("Las Vegas")
                    .status(Event.EventStatus.SCHEDULED)
                    .build());

            Fight fight = fightRepository.save(Fight.builder()
                    .event(event).fighter1(fighter1).fighter2(fighter2)
                    .fightOrder(1)
                    .build());

            log.info("Seeded reference data: event={}, fight={}, fighters=[{}, {}], users=2",
                    event.getEventId(), fight.getFightId(), fighter1.getFighterId(), fighter2.getFighterId());
        };
    }
}
