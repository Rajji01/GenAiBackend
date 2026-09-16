package com.ticketing.inventory.service;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.repository.SeatRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
@RequiredArgsConstructor
public class SeatService {

    private final SeatRepository repo;

    // No such-show validation here on purpose: inventory-service doesn't
    // own the concept of a "show" (catalog-service does, Phase 2) — an
    // unknown showId just has zero seats, which is an honest empty list,
    // not an error.
    public List<Seat> getAvailability(Long showId) {
        return repo.findByShowId(showId);
    }
}
