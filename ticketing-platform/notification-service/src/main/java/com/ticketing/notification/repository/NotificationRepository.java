package com.ticketing.notification.repository;

import com.ticketing.notification.entity.Notification;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface NotificationRepository extends JpaRepository<Notification, Long> {

    List<Notification> findByHolderIdOrderByReceivedAtDesc(String holderId);

    List<Notification> findByBookingIdOrderByReceivedAtDesc(Long bookingId);
}
