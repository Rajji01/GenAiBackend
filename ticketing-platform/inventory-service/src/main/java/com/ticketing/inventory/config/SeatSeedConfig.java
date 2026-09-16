package com.ticketing.inventory.config;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.repository.SeatRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

// Dev-only seed data, same reasoning as backend's ProductSeedConfig: a
// standalone @Configuration class, not a @Bean method on the
// @SpringBootApplication class, so @WebMvcTest slice tests don't drag in
// SeatRepository just to satisfy this bean's dependency.
//
// Temporary stand-in for catalog-service (Phase 2), which will actually own
// show/seat creation. Idempotent on purpose — checks for existing seats
// first, so restarting the app against the same Postgres volume doesn't
// keep inserting duplicate rows (which the unique constraint would reject
// anyway, but loudly, on every restart).
@Configuration
public class SeatSeedConfig {

    private static final Logger log = LoggerFactory.getLogger(SeatSeedConfig.class);
    private static final Long DEMO_SHOW_ID = 1L;
    private static final int DEMO_SEAT_COUNT = 10;

    @Bean
    CommandLineRunner seedDemoSeats(SeatRepository repo) {
        return args -> {
            if (!repo.findByShowId(DEMO_SHOW_ID).isEmpty()) {
                log.info("Demo seats for show {} already seeded, skipping", DEMO_SHOW_ID);
                return;
            }
            for (int i = 1; i <= DEMO_SEAT_COUNT; i++) {
                repo.save(new Seat(DEMO_SHOW_ID, "A" + i));
            }
            log.info("Seeded {} demo seats for show {}", DEMO_SEAT_COUNT, DEMO_SHOW_ID);
        };
    }
}
