package com.ufc.backend.dto;

import com.ufc.backend.entities.WeightClass;

public record WeightClassResponse(
        Long weightClassId,
        String className,
        Double minWeight,
        Double maxWeight
) {
    public static WeightClassResponse from(WeightClass entity) {
        return new WeightClassResponse(
                entity.getWeightClassId(),
                entity.getClassName(),
                entity.getMinWeight(),
                entity.getMaxWeight()
        );
    }
}
