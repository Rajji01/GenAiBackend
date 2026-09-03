package com.ufc.backend.entities;



import jakarta.persistence.*;
import lombok.*;

import java.util.Date;

@Entity
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@Table(name = "Contract")
public class Contract {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long contractId;

    @OneToOne
    @JoinColumn(name = "fighter_id", nullable = false)
    private Fighter fighter;

    private int fightsRemaining;
    private Double basePay;
    private Double winBonus;
    private Double sponsorship;
    private Date contractExpiry;
}

