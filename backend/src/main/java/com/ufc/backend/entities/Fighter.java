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
@Table(name = "Fighter")
public class Fighter {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long fighterId;

    private String firstName;
    private String lastName;
    private String nickname;
    private Date birthDate;
    private String country;
    private Double heightCm;
    private Double reachCm;

    @ManyToOne
    @JoinColumn(name = "weight_class_id", nullable = false)
    private WeightClass weightClass;

    @Enumerated(EnumType.STRING)
    private Stance stance;

    private int recordWins;
    private int recordLosses;
    private int recordDraws;

    public enum Stance {
        ORTHODOX, SOUTHPAW, SWITCH
    }
}
