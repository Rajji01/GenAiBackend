-- Baseline schema for the UFC backend.
-- This mirrors the schema already running in `ufcmain` (originally produced by
-- Hibernate ddl-auto). From this point on, Flyway migrations are the single
-- source of truth for schema changes — Hibernate is set to `validate` only.

CREATE TABLE weight_class (
    weight_class_id BIGINT NOT NULL AUTO_INCREMENT,
    class_name      VARCHAR(255),
    min_weight      DOUBLE,
    max_weight      DOUBLE,
    PRIMARY KEY (weight_class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE user (
    user_id       BIGINT NOT NULL AUTO_INCREMENT,
    username      VARCHAR(255),
    email         VARCHAR(255),
    password_hash VARCHAR(255),
    PRIMARY KEY (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE fighter (
    fighter_id      BIGINT NOT NULL AUTO_INCREMENT,
    first_name      VARCHAR(255),
    last_name       VARCHAR(255),
    nickname        VARCHAR(255),
    birth_date      DATETIME(6),
    country         VARCHAR(255),
    height_cm       DOUBLE,
    reach_cm        DOUBLE,
    weight_class_id BIGINT NOT NULL,
    stance          ENUM('ORTHODOX','SOUTHPAW','SWITCH'),
    record_wins     INT NOT NULL,
    record_losses   INT NOT NULL,
    record_draws    INT NOT NULL,
    PRIMARY KEY (fighter_id),
    CONSTRAINT fk_fighter_weight_class FOREIGN KEY (weight_class_id) REFERENCES weight_class (weight_class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE event (
    event_id   BIGINT NOT NULL AUTO_INCREMENT,
    event_name VARCHAR(255),
    event_date DATETIME(6),
    location   VARCHAR(255),
    status     ENUM('SCHEDULED','ONGOING','COMPLETED'),
    PRIMARY KEY (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE contract (
    contract_id      BIGINT NOT NULL AUTO_INCREMENT,
    fighter_id       BIGINT NOT NULL,
    fights_remaining INT NOT NULL,
    base_pay         DOUBLE,
    win_bonus        DOUBLE,
    sponsorship      DOUBLE,
    contract_expiry  DATETIME(6),
    PRIMARY KEY (contract_id),
    UNIQUE KEY uk_contract_fighter (fighter_id),
    CONSTRAINT fk_contract_fighter FOREIGN KEY (fighter_id) REFERENCES fighter (fighter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE fight (
    fight_id    BIGINT NOT NULL AUTO_INCREMENT,
    event_id    BIGINT NOT NULL,
    fighter1_id BIGINT NOT NULL,
    fighter2_id BIGINT NOT NULL,
    winner_id   BIGINT,
    method      ENUM('KO','TKO','SUBMISSION','DECISION','DRAW','NO_CONTEST'),
    round_ended INT,
    time_ended  VARCHAR(255),
    fight_order INT,
    PRIMARY KEY (fight_id),
    CONSTRAINT fk_fight_event FOREIGN KEY (event_id) REFERENCES event (event_id),
    CONSTRAINT fk_fight_fighter1 FOREIGN KEY (fighter1_id) REFERENCES fighter (fighter_id),
    CONSTRAINT fk_fight_fighter2 FOREIGN KEY (fighter2_id) REFERENCES fighter (fighter_id),
    CONSTRAINT fk_fight_winner FOREIGN KEY (winner_id) REFERENCES fighter (fighter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE bet (
    bet_id     BIGINT NOT NULL AUTO_INCREMENT,
    user_id    BIGINT NOT NULL,
    fight_id   BIGINT NOT NULL,
    fighter_id BIGINT NOT NULL,
    amount     DOUBLE,
    odds       DOUBLE,
    status     ENUM('PENDING','WON','LOST'),
    PRIMARY KEY (bet_id),
    CONSTRAINT fk_bet_user FOREIGN KEY (user_id) REFERENCES user (user_id),
    CONSTRAINT fk_bet_fight FOREIGN KEY (fight_id) REFERENCES fight (fight_id),
    CONSTRAINT fk_bet_fighter FOREIGN KEY (fighter_id) REFERENCES fighter (fighter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE comment (
    comment_id   BIGINT NOT NULL AUTO_INCREMENT,
    user_id      BIGINT NOT NULL,
    fight_id     BIGINT NOT NULL,
    comment_text VARCHAR(500),
    created_at   DATETIME(6),
    PRIMARY KEY (comment_id),
    CONSTRAINT fk_comment_user FOREIGN KEY (user_id) REFERENCES user (user_id),
    CONSTRAINT fk_comment_fight FOREIGN KEY (fight_id) REFERENCES fight (fight_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE fight_stats (
    stats_id              BIGINT NOT NULL AUTO_INCREMENT,
    fight_id              BIGINT NOT NULL,
    fighter_id            BIGINT NOT NULL,
    strikes_attempted     INT NOT NULL,
    strikes_landed        INT NOT NULL,
    takedowns_attempted   INT NOT NULL,
    takedowns_successful  INT NOT NULL,
    submission_attempts   INT NOT NULL,
    control_time_seconds  INT NOT NULL,
    PRIMARY KEY (stats_id),
    CONSTRAINT fk_fightstats_fight FOREIGN KEY (fight_id) REFERENCES fight (fight_id),
    CONSTRAINT fk_fightstats_fighter FOREIGN KEY (fighter_id) REFERENCES fighter (fighter_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Sandbox entity used for the optimistic-locking exploration (com.ufc.backend.optimistic.locking).
CREATE TABLE product (
    id      BIGINT NOT NULL AUTO_INCREMENT,
    name    VARCHAR(255),
    stock   INT,
    version BIGINT,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
