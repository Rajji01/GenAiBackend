package com.ufc.backend.dto;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record WeightClassRequest(

        @NotBlank(message = "className is required")
        String className,

        @NotNull(message = "minWeight is required")
        @Positive(message = "minWeight must be greater than 0")
        Double minWeight,

        @NotNull(message = "maxWeight is required")
        @Positive(message = "maxWeight must be greater than 0")
        Double maxWeight
) {
    @AssertTrue(message = "maxWeight must be greater than minWeight")
    public boolean isWeightRangeValid() {
        if (minWeight == null || maxWeight == null) {
            return true; // let @NotNull report the real problem instead of a confusing double error
        }
        return maxWeight > minWeight;
    }
}
