package com.ufc.backend.entities;



import jakarta.persistence.*;
import lombok.*;

@Entity
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@Table(name = "Fight")
public class Fight {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long fightId;

    @ManyToOne
    @JoinColumn(name = "event_id", nullable = false)
    private Event event;

    @ManyToOne
    @JoinColumn(name = "fighter1_id", nullable = false)
    private Fighter fighter1;

    @ManyToOne
    @JoinColumn(name = "fighter2_id", nullable = false)
    private Fighter fighter2;

    @ManyToOne
    @JoinColumn(name = "winner_id")
    private Fighter winner;

    @Enumerated(EnumType.STRING)
    private Method method;

    private Integer roundEnded;
    private String timeEnded; // Format: MM:SS
    private Integer fightOrder;

    public enum Method {
        KO, TKO, SUBMISSION, DECISION, DRAW, NO_CONTEST
    }
}
