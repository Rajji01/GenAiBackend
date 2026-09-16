package com.ticketing.inventory.dto;

public record HoldResponse(Long seatId, String holderId, long ttlSeconds) {
}
