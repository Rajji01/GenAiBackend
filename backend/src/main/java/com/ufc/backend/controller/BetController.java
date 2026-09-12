package com.ufc.backend.controller;

import com.ufc.backend.dto.BetAmountUpdateRequest;
import com.ufc.backend.dto.BetRequest;
import com.ufc.backend.dto.BetResponse;
import com.ufc.backend.service.BetService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/bets")
@RequiredArgsConstructor
public class BetController {

    private final BetService betService;

    // POST /bets -> place a new bet
    @PostMapping
    public ResponseEntity<BetResponse> placeBet(@Valid @RequestBody BetRequest request) {
        BetResponse created = betService.placeBet(request);
        return ResponseEntity.status(HttpStatus.CREATED).body(created);
    }

    // PATCH /bets/{id}/amount -> change the wagered amount on an existing,
    // still-pending bet. This is the operation where two concurrent requests
    // for the same bet can race — see BetConcurrencyTest.
    @PatchMapping("/{id}/amount")
    public ResponseEntity<BetResponse> updateAmount(
            @PathVariable Long id, @Valid @RequestBody BetAmountUpdateRequest request) {
        return ResponseEntity.ok(betService.updateBetAmount(id, request));
    }
}
