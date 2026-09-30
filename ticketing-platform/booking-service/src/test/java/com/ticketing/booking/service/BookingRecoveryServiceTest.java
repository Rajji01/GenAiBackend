package com.ticketing.booking.service;

import com.ticketing.booking.client.InventoryClient;
import com.ticketing.booking.client.PaymentClient;
import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingSeat;
import com.ticketing.booking.entity.BookingStatus;
import com.ticketing.booking.outbox.OutboxService;
import com.ticketing.booking.repository.BookingRepository;
import com.ticketing.booking.repository.BookingSeatRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

// Dangling-saga recovery (WEEK3_DESIGN.md §5). recover(booking) is driven
// per-status; each branch either rolls the booking back cleanly or drives it
// forward. All collaborators mocked, the write-tx runs its lambda through a
// mocked PlatformTransactionManager (see PaymentServiceTest note), so the
// whole recovery decision tree is exercised without a DB or Docker.
class BookingRecoveryServiceTest {

    private BookingRepository bookingRepository;
    private BookingSeatRepository seatRepository;
    private InventoryClient inventoryClient;
    private PaymentClient paymentClient;
    private OutboxService outboxService;
    private BookingRecoveryService service;

    @BeforeEach
    void setUp() {
        bookingRepository = mock(BookingRepository.class);
        seatRepository = mock(BookingSeatRepository.class);
        inventoryClient = mock(InventoryClient.class);
        paymentClient = mock(PaymentClient.class);
        outboxService = mock(OutboxService.class);
        PlatformTransactionManager txManager = mock(PlatformTransactionManager.class);
        service = new BookingRecoveryService(bookingRepository, seatRepository,
                inventoryClient, paymentClient, outboxService, txManager);
    }

    // ---- helpers ----

    private static void setId(Booking b, long id) {
        ReflectionTestUtils.setField(b, "id", id);
    }

    private Booking pending(long id) {
        Booking b = new Booking("key-" + id, "hash-" + id, 10L, "user-" + id);
        setId(b, id);
        return b;
    }

    private Booking seatsHeld(long id) {
        Booking b = pending(id);
        b.markSeatsHeld();
        return b;
    }

    private Booking paymentInitiated(long id, Long paymentId) {
        Booking b = seatsHeld(id);
        b.markPaymentInitiated(paymentId, "pay-" + paymentId);
        return b;
    }

    private PaymentClient.PaymentResponse payment(String status) {
        return new PaymentClient.PaymentResponse(
                99L, 1L, "u", new BigDecimal("100.00"), "INR", "UPI",
                status, "gw-ref", Instant.now(), null, null, null);
    }

    // ---- PENDING: nothing happened, safe to fail immediately ----

    @Test
    void recover_pending_marksFailedWithoutTouchingDownstream() {
        Booking b = pending(1);
        when(bookingRepository.findById(1L)).thenReturn(Optional.of(b));

        service.recover(b);

        assertThat(b.getStatus()).isEqualTo(BookingStatus.FAILED);
        verifyNoInteractions(inventoryClient, paymentClient, outboxService);
    }

    // ---- SEATS_HELD: release holds + fail ----

    @Test
    void recover_seatsHeld_releasesEachSeatThenMarksFailed() {
        Booking b = seatsHeld(2);
        when(seatRepository.findByBookingId(2L))
                .thenReturn(List.of(new BookingSeat(2L, 5L), new BookingSeat(2L, 6L)));
        when(bookingRepository.findById(2L)).thenReturn(Optional.of(b));

        service.recover(b);

        verify(inventoryClient).release(10L, 5L, "user-2");
        verify(inventoryClient).release(10L, 6L, "user-2");
        assertThat(b.getStatus()).isEqualTo(BookingStatus.FAILED);
        verifyNoInteractions(paymentClient);
    }

    // ---- PAYMENT_INITIATED branches ----

    @Test
    void recover_paymentInitiated_paymentCaptured_confirmsSeatsAndRecordsOutbox() {
        Booking b = paymentInitiated(3, 99L);
        when(paymentClient.getById(99L)).thenReturn(payment("CAPTURED"));
        when(seatRepository.findByBookingId(3L)).thenReturn(List.of(new BookingSeat(3L, 5L)));
        when(bookingRepository.findById(3L)).thenReturn(Optional.of(b));

        service.recover(b);

        verify(inventoryClient).confirm(10L, 5L, "user-3");
        assertThat(b.getStatus()).isEqualTo(BookingStatus.CONFIRMED);
        verify(outboxService).record(eq("3"), eq("BookingConfirmed"), any());
    }

    @Test
    void recover_paymentInitiated_paymentFailed_releasesSeatsAndMarksFailed() {
        Booking b = paymentInitiated(4, 88L);
        when(paymentClient.getById(88L)).thenReturn(payment("FAILED"));
        when(seatRepository.findByBookingId(4L)).thenReturn(List.of(new BookingSeat(4L, 7L)));
        when(bookingRepository.findById(4L)).thenReturn(Optional.of(b));

        service.recover(b);

        verify(inventoryClient).release(10L, 7L, "user-4");
        assertThat(b.getStatus()).isEqualTo(BookingStatus.FAILED);
        verifyNoInteractions(outboxService);
    }

    @Test
    void recover_paymentInitiated_missingPaymentId_fallsBackToSeatRelease() {
        // Defensive branch: PAYMENT_INITIATED with a null payment id can't be
        // queried, so it's treated exactly like SEATS_HELD — release + fail.
        Booking b = paymentInitiated(5, null);
        when(seatRepository.findByBookingId(5L)).thenReturn(List.of(new BookingSeat(5L, 8L)));
        when(bookingRepository.findById(5L)).thenReturn(Optional.of(b));

        service.recover(b);

        verify(inventoryClient).release(10L, 8L, "user-5");
        assertThat(b.getStatus()).isEqualTo(BookingStatus.FAILED);
        verifyNoInteractions(paymentClient);
    }

    @Test
    void recover_capturedButConfirmFails_refundAlsoFails_marksFailedRefundPending() {
        Booking b = paymentInitiated(6, 77L);
        when(paymentClient.getById(77L)).thenReturn(payment("CAPTURED"));
        when(seatRepository.findByBookingId(6L)).thenReturn(List.of(new BookingSeat(6L, 9L)));
        doThrow(new RuntimeException("inventory down"))
                .when(inventoryClient).confirm(10L, 9L, "user-6");
        doThrow(new RuntimeException("refund gateway down"))
                .when(paymentClient).refund(eq(77L), anyString());
        when(bookingRepository.findById(6L)).thenReturn(Optional.of(b));

        service.recover(b);

        // Money moved but confirm failed and the auto-refund also failed →
        // the booking is FAILED but flagged so the ops queue owes a refund.
        assertThat(b.getStatus()).isEqualTo(BookingStatus.FAILED);
        assertThat(b.isRefundPending()).isTrue();
    }
}
