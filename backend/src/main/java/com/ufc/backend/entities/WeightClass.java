package com.ufc.backend.entities;


import jakarta.persistence.*;
import lombok.*;

import java.util.List;

@Entity
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@Table(name = "WeightClass")
public class WeightClass {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long weightClassId;

    private String className;
    private Double minWeight;
    private Double maxWeight;

    @OneToMany(mappedBy = "weightClass")
    private List<Fighter> fighters;
}
