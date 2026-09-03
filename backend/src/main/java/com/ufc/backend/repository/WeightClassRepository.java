package com.ufc.backend.repository;


import com.ufc.backend.dto.WeightClassProjection;
import com.ufc.backend.entities.WeightClass;
import jakarta.persistence.QueryHint;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.jpa.repository.QueryHints;
import org.springframework.stereotype.Repository;

import java.util.stream.Stream;

@Repository
public interface WeightClassRepository extends JpaRepository<WeightClass, Long> {

    // Fetch Weight Classes with Pagination and Sorting
    Page<WeightClassProjection> findAllProjectedBy(Pageable pageable);

    // Fetch Weight Classes as a Stream (Efficient for large data)
    @Query("SELECT w FROM WeightClass w")
    @QueryHints(@QueryHint(name = "org.hibernate.fetchSize", value = "1"))
    Stream<WeightClass> streamAllWeightClasses();
}

