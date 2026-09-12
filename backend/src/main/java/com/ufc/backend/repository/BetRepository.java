package com.ufc.backend.repository;

import com.ufc.backend.entities.Bet;
import org.springframework.data.jpa.repository.JpaRepository;

public interface BetRepository extends JpaRepository<Bet, Long> {
}
