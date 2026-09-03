package com.ufc.backend.entities;



import jakarta.persistence.*;
import lombok.*;

@Entity
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@Table(name = "FightStats")
public class FightStats {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long statsId;

    @ManyToOne
    @JoinColumn(name = "fight_id", nullable = false)
    private Fight fight;

    @ManyToOne
    @JoinColumn(name = "fighter_id", nullable = false)
    private Fighter fighter;

    private int strikesAttempted;
    private int strikesLanded;
    private int takedownsAttempted;
    private int takedownsSuccessful;
    private int submissionAttempts;
    private int controlTimeSeconds;
}
