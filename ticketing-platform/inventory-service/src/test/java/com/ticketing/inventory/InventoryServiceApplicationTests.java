package com.ticketing.inventory;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import com.redis.testcontainers.RedisContainer;

// Real Postgres + Redis via Testcontainers, not H2/embedded fakes — the
// whole point of Week 1 is proving concurrency behaviour that an
// in-memory substitute wouldn't reproduce faithfully. Same principle as
// narration-enrichment's StaticPool lesson, in reverse: don't let a
// convenient fake hide behaviour the real dependency actually has.
//
// "test" profile disables HoldReconciliationService's background sweep
// (see application-test.yml) — without it, this context's live scheduler
// can fire after these Testcontainers are torn down and throw into the
// logs (harmless to this test's own assertions, but noisy and a real
// symptom of a context-caching/teardown-ordering risk worth avoiding).
@SpringBootTest
@ActiveProfiles("test")
@Testcontainers
class InventoryServiceApplicationTests {

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

	@Test
	void contextLoads() {
		// Deliberately empty: the assertion IS that Spring can wire the
		// whole application context against real Postgres + Redis
		// containers without throwing. No entities/repositories exist
		// yet (Day 2) — this just proves the skeleton itself is sound
		// before anything is built on top of it.
	}

}
