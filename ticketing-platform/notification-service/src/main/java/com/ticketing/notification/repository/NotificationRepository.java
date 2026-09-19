package com.ticketing.notification.repository;

import com.ticketing.notification.entity.Notification;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface NotificationRepository extends JpaRepository<Notification, Long> {

    // Week 3 Day 7 — dedup lookup. Called on the receive path; if it
    // returns present, the event has been seen before → skip.
    Optional<Notification> findByEventId(String eventId);

    List<Notification> findByHolderIdOrderByReceivedAtDesc(String holderId);

    List<Notification> findByBookingIdOrderByReceivedAtDesc(Long bookingId);
}
