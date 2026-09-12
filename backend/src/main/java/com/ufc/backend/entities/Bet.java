package com.ufc.backend.entities;



import jakarta.persistence.*;
import lombok.*;

@Entity
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@Table(name = "Bet")
public class Bet {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long betId;

    @ManyToOne
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @ManyToOne
    @JoinColumn(name = "fight_id", nullable = false)
    private Fight fight;

    @ManyToOne
    @JoinColumn(name = "fighter_id", nullable = false)
    private Fighter fighter;

    private Double amount;
    private Double odds;

    @Enumerated(EnumType.STRING)
    private BetStatus status;

    @Version
    private Long version;

    public enum BetStatus {
        PENDING, WON, LOST
    }
}
