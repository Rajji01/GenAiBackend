package com.ufc.backend.optimistic.locking;


import com.ufc.backend.exception.ConflictException;
import com.ufc.backend.exception.ResourceNotFoundException;
import jakarta.persistence.EntityManager;
import jakarta.persistence.LockModeType;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class ProductService {

    private final ProductRepository repo;
    private final EntityManager em;

    @Transactional
    public void buyOne(Long productId) {
        Product p = repo.findById(productId)
                .orElseThrow(() -> new ResourceNotFoundException("Product not found: " + productId));
        if (p.getStock() <= 0) {
            throw new ConflictException("Product is sold out: " + productId);
        }
        p.setStock(p.getStock() - 1);
        // on commit, Hibernate will include version in WHERE clause
        // if another tx updated meanwhile, this save will fail
        repo.save(p);
    }
    @Transactional
    public void buyOneOptimisticRepo(Long id) {
        Product p = repo.findWithOptimistic(id);
        if (p == null) {
            throw new ResourceNotFoundException("Product not found: " + id);
        }
        if (p.getStock() <= 0) {
            throw new ConflictException("Product is sold out: " + id);
        }
        p.setStock(p.getStock() - 1);
        // on commit, Hibernate will include version in WHERE clause
        // if another tx updated meanwhile, this save will fail
        repo.save(p);
    }

    @Transactional
    public void buyOneForceIncrementRepo(Long id) {
        Product p = repo.findWithForceIncrement(id);
        if (p == null) {
            throw new ResourceNotFoundException("Product not found: " + id);
        }
        if (p.getStock() <= 0) {
            throw new ConflictException("Product is sold out: " + id);
        }
        p.setStock(p.getStock() - 1);
        // on commit, Hibernate will include version in WHERE clause
        // if another tx updated meanwhile, this save will fail
        repo.save(p);
    }
    @Transactional
    public void buyOneOptimistic(Long productId) {
        // 1. Acquire an optimistic *read* lock (no version bump yet)
        Product p = em.find(Product.class, productId, LockModeType.OPTIMISTIC);
        if (p == null) {
            throw new ResourceNotFoundException("Product not found: " + productId);
        }
        if (p.getStock() <= 0) throw new ConflictException("Product is sold out: " + productId);
        p.setStock(p.getStock() - 1);

        // on commit, version is *validated* but not bumped by this lock
        repo.save(p);
    }

    @Transactional
    public void buyOneForceIncrement(Long productId) {
        // 1. Acquire optimistic *force-increment* lock (version++)
        Product p = em.find(Product.class, productId, LockModeType.OPTIMISTIC_FORCE_INCREMENT);
        if (p == null) {
            throw new ResourceNotFoundException("Product not found: " + productId);
        }
        if (p.getStock() <= 0) throw new ConflictException("Product is sold out: " + productId);
        p.setStock(p.getStock() - 1);

        // version was already scheduled to ++ at flush
        repo.save(p);
    }

}
