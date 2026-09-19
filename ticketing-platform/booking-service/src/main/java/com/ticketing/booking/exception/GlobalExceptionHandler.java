package com.ticketing.booking.exception;

import com.ticketing.booking.service.BookingSagaService.SagaFailedException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import java.util.LinkedHashMap;
import java.util.Map;

// Same shape as inventory-service's GlobalExceptionHandler (RFC 7807
// ProblemDetail). Deliberately copied, not extracted into a shared library —
// a shared lib across services couples their deploy cycles for a class of
// change (add a new exception mapping) that would otherwise be independent.
// The duplication is cheap, the coupling is not.
@RestControllerAdvice
public class GlobalExceptionHandler extends ResponseEntityExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @Override
    protected ResponseEntity<Object> handleMethodArgumentNotValid(
            MethodArgumentNotValidException ex, HttpHeaders headers, HttpStatusCode status, WebRequest request) {

        Map<String, String> fieldErrors = new LinkedHashMap<>();
        for (FieldError fieldError : ex.getBindingResult().getFieldErrors()) {
            fieldErrors.put(fieldError.getField(), fieldError.getDefaultMessage());
        }

        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.BAD_REQUEST, "One or more fields failed validation");
        problem.setTitle("Validation Failed");
        problem.setProperty("errors", fieldErrors);

        log.warn("Validation failed: {}", fieldErrors);
        return ResponseEntity.badRequest().body(problem);
    }

    @ExceptionHandler(MissingRequestHeaderException.class)
    public ProblemDetail handleMissingHeader(MissingRequestHeaderException ex) {
        // The only required header today is Idempotency-Key on POST /bookings
        // (WEEK2_DESIGN.md §5: "no key = 400. The endpoint refuses to be
        // non-idempotent."). Using @ExceptionHandler directly instead of
        // overriding ResponseEntityExceptionHandler's method — the latter's
        // signature has shifted across Spring versions, and this is the
        // stabler seam.
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.BAD_REQUEST, "Missing required header: " + ex.getHeaderName());
        problem.setTitle("Missing Header");
        log.warn("Missing header: {}", ex.getHeaderName());
        return problem;
    }

    @ExceptionHandler(ResourceNotFoundException.class)
    public ProblemDetail handleNotFound(ResourceNotFoundException ex) {
        log.warn("Resource not found: {}", ex.getMessage());
        return ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, ex.getMessage());
    }

    @ExceptionHandler(IdempotencyKeyReuseException.class)
    public ProblemDetail handleIdempotencyKeyReuse(IdempotencyKeyReuseException ex) {
        // 422, not 409: see the class-level comment on IdempotencyKeyReuseException.
        log.warn("Idempotency-Key reuse with different body: {}", ex.getMessage());
        return ProblemDetail.forStatusAndDetail(HttpStatus.UNPROCESSABLE_ENTITY, ex.getMessage());
    }

    @ExceptionHandler(OptimisticLockingFailureException.class)
    public ProblemDetail handleOptimisticLocking(OptimisticLockingFailureException ex) {
        log.warn("Optimistic locking conflict on booking row: {}", ex.getMessage());
        return ProblemDetail.forStatusAndDetail(
                HttpStatus.CONFLICT, "This booking was modified by another request. Please retry.");
    }

    @ExceptionHandler(SagaFailedException.class)
    public ResponseEntity<ProblemDetail> handleSagaFailed(SagaFailedException ex) {
        // 502 Bad Gateway: booking-service itself is fine, but a downstream
        // dependency (inventory or payment) prevented completion. The row
        // IS persisted as FAILED — the bookingId is included so the client
        // can GET /bookings/{id} to inspect. See WEEK2_DESIGN.md §6.
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.BAD_GATEWAY,
                "Booking could not be completed: " + ex.getMessage());
        problem.setTitle("Saga Failed");
        problem.setProperty("bookingId", ex.getBookingId());
        log.warn("Saga failed bookingId={} reason={}", ex.getBookingId(), ex.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(problem);
    }

    @ExceptionHandler(Exception.class)
    public ProblemDetail handleUnexpected(Exception ex) {
        log.error("Unhandled exception", ex);
        return ProblemDetail.forStatusAndDetail(
                HttpStatus.INTERNAL_SERVER_ERROR, "An unexpected error occurred");
    }
}
