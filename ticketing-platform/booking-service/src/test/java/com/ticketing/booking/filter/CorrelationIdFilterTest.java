package com.ticketing.booking.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.io.IOException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assertions.assertThrows;

// Same three-test spec as inventory-service's filter test: incoming header
// reused; missing header → new UUID; MDC cleared even if the chain throws.
class CorrelationIdFilterTest {

    private final CorrelationIdFilter filter = new CorrelationIdFilter();

    @AfterEach
    void clearMdc() {
        MDC.clear();
    }

    @Test
    void anIncomingCorrelationIdIsPreservedAndEchoedBack() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest();
        req.addHeader(CorrelationIdFilter.HEADER, "incoming-123");
        MockHttpServletResponse res = new MockHttpServletResponse();

        filter.doFilter(req, res, capturingMdc(id -> assertThat(id).isEqualTo("incoming-123")));

        assertThat(res.getHeader(CorrelationIdFilter.HEADER)).isEqualTo("incoming-123");
        assertThat(MDC.get(CorrelationIdFilter.MDC_KEY)).isNull();
    }

    @Test
    void aMissingHeaderCausesAFreshUuidToBeGeneratedAndReturned() throws Exception {
        MockHttpServletRequest req = new MockHttpServletRequest();
        MockHttpServletResponse res = new MockHttpServletResponse();

        filter.doFilter(req, res, (rq, rs) -> {
            assertThat(MDC.get(CorrelationIdFilter.MDC_KEY)).isNotBlank();
        });

        assertThat(res.getHeader(CorrelationIdFilter.HEADER)).isNotBlank();
    }

    @Test
    void mdcIsClearedEvenIfTheChainThrows() {
        MockHttpServletRequest req = new MockHttpServletRequest();
        MockHttpServletResponse res = new MockHttpServletResponse();

        assertThrows(ServletException.class, () -> filter.doFilter(req, res, (rq, rs) -> {
            throw new ServletException("boom");
        }));

        assertThat(MDC.get(CorrelationIdFilter.MDC_KEY)).isNull();
    }

    private FilterChain capturingMdc(java.util.function.Consumer<String> assertion) {
        return (request, response) -> assertion.accept(MDC.get(CorrelationIdFilter.MDC_KEY));
    }
}
