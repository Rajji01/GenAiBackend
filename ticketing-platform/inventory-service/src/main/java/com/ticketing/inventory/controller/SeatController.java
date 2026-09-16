package com.ticketing.inventory.controller;

import com.ticketing.inventory.dto.SeatResponse;
import com.ticketing.inventory.service.SeatService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/shows/{showId}/seats")
@RequiredArgsConstructor
public class SeatController {

    private final SeatService seatService;

    @GetMapping("/availability")
    public List<SeatResponse> availability(@PathVariable Long showId) {
        return seatService.getAvailability(showId).stream()
                .map(SeatResponse::from)
                .toList();
    }
}
