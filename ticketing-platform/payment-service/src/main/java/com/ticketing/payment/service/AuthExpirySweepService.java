package com.ticketing.payment.service;

import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

// Self-heal: any payment stuck in AUTHORIZED longer than
// payment.auth.window-hours gets voided. Real gateways auto-expire auths
// on their side, but we still need to reflect that in payment-service's
// own DB so a stale AUTHORIZED row is not read as "still valid" by
// booking-service's recovery sweep.
//
// Same design choice as inventory-service's HoldReconciliationService:
// polling, not events. A missed event during app restart would leave
// authorizations stuck AUTHORIZED forever; polling self-heals.
@Service
@RequiredArgsConstructor
public class AuthExpirySweepService {

    private static final Logger log = LoggerFactory.getLogger(AuthExpirySweepService.class);

    private final PaymentService paymentService;

    // Every 60 seconds. Real prod could tune this to line up with the
    // auth window; 60s is fast enough that a stale auth becomes visible
    // to a booking-service recovery pass within the same minute.
    @Scheduled(fixedDelayString = "${payment.auth.sweep-interval-ms:60000}")
    public void sweep() {
        var expired = paymentService.findExpiredAuthorizations();
        if (expired.isEmpty()) return;
        log.info("auth_expiry_sweep found={}", expired.size());
        for (Long id : expired) {
            paymentService.voidExpiredAuthorization(id);
        }
    }
}
