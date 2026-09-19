package com.ticketing.inventory.dto;

public record ConfirmResponse(Long seatId, String holderId, String status) {
}
