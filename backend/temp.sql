-- SUPERSEDED: this script is no longer the source of truth for the schema and
-- was never actually consistent with the real database (it targets `ufc_db`,
-- but the app connects to `ufcmain`, and the columns/naming here don't match
-- what Hibernate actually generated). The real, versioned schema now lives in
-- src/main/resources/db/migration/V1__baseline_schema.sql (Flyway). Kept here
-- only as historical reference of the originally intended design.

-- UFC Database Schema (original, unused draft)

CREATE DATABASE ufc_db;
USE ufc_db;

-- Table: Fighters
CREATE TABLE Fighter (
    fighter_id INT PRIMARY KEY AUTO_INCREMENT,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    nickname VARCHAR(50),
    birth_date DATE,
    country VARCHAR(50),
    height_cm DECIMAL(5,2),
    reach_cm DECIMAL(5,2),
    weight_class_id INT,
    stance ENUM('Orthodox', 'Southpaw', 'Switch'),
    record_wins INT DEFAULT 0,
    record_losses INT DEFAULT 0,
    record_draws INT DEFAULT 0,
    FOREIGN KEY (weight_class_id) REFERENCES WeightClass(weight_class_id)
);

-- Table: Weight Classes
CREATE TABLE WeightClass (
    weight_class_id INT PRIMARY KEY AUTO_INCREMENT,
    class_name VARCHAR(50) UNIQUE NOT NULL,
    min_weight DECIMAL(5,2),
    max_weight DECIMAL(5,2)
);

-- Table: UFC Events
CREATE TABLE Event (
    event_id INT PRIMARY KEY AUTO_INCREMENT,
    event_name VARCHAR(100) NOT NULL,
    event_date DATE NOT NULL,
    location VARCHAR(100),
    main_event_fight_id INT NULL,
    status ENUM('Scheduled', 'Ongoing', 'Completed') DEFAULT 'Scheduled'
);

-- Table: Fights
CREATE TABLE Fight (
    fight_id INT PRIMARY KEY AUTO_INCREMENT,
    event_id INT NOT NULL,
    fighter1_id INT NOT NULL,
    fighter2_id INT NOT NULL,
    winner_id INT NULL,
    method ENUM('KO', 'TKO', 'Submission', 'Decision', 'Draw', 'No Contest'),
    round_ended INT NULL,
    time_ended TIME NULL,
    fight_order INT NOT NULL, -- Order of the fight in the event
    FOREIGN KEY (event_id) REFERENCES Event(event_id),
    FOREIGN KEY (fighter1_id) REFERENCES Fighter(fighter_id),
    FOREIGN KEY (fighter2_id) REFERENCES Fighter(fighter_id),
    FOREIGN KEY (winner_id) REFERENCES Fighter(fighter_id)
);

-- Table: Fight Stats (Real-time fight tracking)
CREATE TABLE FightStats (
    stats_id INT PRIMARY KEY AUTO_INCREMENT,
    fight_id INT NOT NULL,
    fighter_id INT NOT NULL,
    strikes_attempted INT DEFAULT 0,
    strikes_landed INT DEFAULT 0,
    takedowns_attempted INT DEFAULT 0,
    takedowns_successful INT DEFAULT 0,
    submission_attempts INT DEFAULT 0,
    control_time_seconds INT DEFAULT 0,
    FOREIGN KEY (fight_id) REFERENCES Fight(fight_id),
    FOREIGN KEY (fighter_id) REFERENCES Fighter(fighter_id)
);

-- Table: Fighter Contracts
CREATE TABLE Contract (
    contract_id INT PRIMARY KEY AUTO_INCREMENT,
    fighter_id INT NOT NULL,
    fights_remaining INT DEFAULT 0,
    base_pay DECIMAL(10,2) NOT NULL,
    win_bonus DECIMAL(10,2) NOT NULL,
    sponsorship DECIMAL(10,2),
    contract_expiry DATE NOT NULL,
    FOREIGN KEY (fighter_id) REFERENCES Fighter(fighter_id)
);

-- Table: Users (Fans)
CREATE TABLE User (
    user_id INT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table: Comments (User Engagement)
CREATE TABLE Comment (
    comment_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    fight_id INT NOT NULL,
    comment_text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES User(user_id),
    FOREIGN KEY (fight_id) REFERENCES Fight(fight_id)
);

-- Table: Bets (User Wagering)
CREATE TABLE Bet (
    bet_id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    fight_id INT NOT NULL,
    fighter_id INT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    odds DECIMAL(5,2) NOT NULL,
    status ENUM('Pending', 'Won', 'Lost') DEFAULT 'Pending',
    FOREIGN KEY (user_id) REFERENCES User(user_id),
    FOREIGN KEY (fight_id) REFERENCES Fight(fight_id),
    FOREIGN KEY (fighter_id) REFERENCES Fighter(fighter_id)
);
