package com.ufc.backend.dto;

public interface WeightClassProjection {
    Long getWeightClassId();
    String getClassName();
    Double getMinWeight();
    Double getMaxWeight();
}