package com.ufc.backend.repository;

import com.ufc.backend.entities.Fight;
import org.springframework.data.jpa.repository.JpaRepository;

public interface FightRepository extends JpaRepository<Fight, Long> {
}
