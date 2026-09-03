package com.ufc.backend.optimistic.locking;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Dev-only seed data for the optimistic-locking sandbox. Kept as its own
 * configuration class (instead of a @Bean on BackendApplication) so that
 * web-layer slice tests (@WebMvcTest) don't drag in ProductRepository just to
 * satisfy this bean's dependency — a plain @Bean method defined directly on
 * the @SpringBootApplication class is NOT filtered out by @WebMvcTest the way
 * @Component-scanned beans are.
 */
@Configuration
public class ProductSeedConfig {

    private static final Logger log = LoggerFactory.getLogger(ProductSeedConfig.class);

    @Bean
    CommandLineRunner seedProduct(ProductRepository repo) {
        return args -> {
            Product p = new Product();
            p.setName("Widget");
            p.setStock(1);
            repo.save(p);
            log.info("Created product with ID={}", p.getId());
        };
    }
}
