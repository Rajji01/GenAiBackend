package com.ticketing.inventory.controller;

import com.ticketing.inventory.dto.HoldRequest;
import com.ticketing.inventory.dto.HoldResponse;
import com.ticketing.inventory.dto.ConfirmRequest;
import com.ticketing.inventory.dto.ConfirmResponse;
import com.ticketing.inventory.dto.ReleaseRequest;
import com.ticketing.inventory.service.HoldService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/shows/{showId}/seats/{seatId}")
@RequiredArgsConstructor
public class HoldController {

    private final HoldService holdService;

    @PostMapping("/hold")
    public HoldResponse hold(
            @PathVariable Long showId,
            @PathVariable Long seatId,
            @Valid @RequestBody HoldRequest request) {
        return holdService.hold(showId, seatId, request.holderId());
    }

    @PostMapping("/confirm")
    public ConfirmResponse confirm(
            @PathVariable Long showId,
            @PathVariable Long seatId,
            @Valid @RequestBody ConfirmRequest request) {
        return holdService.confirm(showId, seatId, request.holderId());
    }

    @PostMapping("/release")
    public ResponseEntity<Void> release(
            @PathVariable Long showId,
            @PathVariable Long seatId,
            @Valid @RequestBody ReleaseRequest request) {
        holdService.release(showId, seatId, request.holderId());
        return ResponseEntity.noContent().build();
    }
}
