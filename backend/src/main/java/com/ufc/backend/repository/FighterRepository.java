package com.ufc.backend.repository;

import com.ufc.backend.entities.Fighter;
import org.springframework.data.jpa.repository.JpaRepository;

public interface FighterRepository extends JpaRepository<Fighter, Long> {
}
