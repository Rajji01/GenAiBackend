package com.ticketing.booking.repository;

import com.ticketing.booking.entity.BookingSeat;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface BookingSeatRepository extends JpaRepository<BookingSeat, Long> {

    List<BookingSeat> findByBookingId(Long bookingId);
}
