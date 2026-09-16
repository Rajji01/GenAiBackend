package com.ticketing.inventory.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.slf4j.MDC;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

class CorrelationIdFilterTest {

    private final CorrelationIdFilter filter = new CorrelationIdFilter();

    @Test
    void generatesACorrelationId_whenTheRequestHasNone() throws Exception {
        HttpServletRequest request = mock(HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);
        FilterChain chain = mock(FilterChain.class);
        when(request.getHeader(CorrelationIdFilter.HEADER_NAME)).thenReturn(null);

        filter.doFilter(request, response, chain);

        ArgumentCaptor<String> headerValue = ArgumentCaptor.forClass(String.class);
        verify(response).setHeader(eq(CorrelationIdFilter.HEADER_NAME), headerValue.capture());
        assertThat(headerValue.getValue()).isNotBlank();
        verify(chain).doFilter(request, response);
        // MDC must not leak past the request — the whole point of the
        // finally block, on a thread this test itself might share with
        // a later test via a pooled executor.
        assertThat(MDC.get(CorrelationIdFilter.MDC_KEY)).isNull();
    }

    @Test
    void reusesAnIncomingCorrelationId_insteadOfGeneratingANewOne() throws Exception {
        HttpServletRequest request = mock(HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);
        FilterChain chain = mock(FilterChain.class);
        when(request.getHeader(CorrelationIdFilter.HEADER_NAME)).thenReturn("caller-supplied-id");

        filter.doFilter(request, response, chain);

        verify(response).setHeader(CorrelationIdFilter.HEADER_NAME, "caller-supplied-id");
    }

    @Test
    void putsTheCorrelationIdInMdc_forTheDurationOfTheChainOnly() throws Exception {
        HttpServletRequest request = mock(HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);
        when(request.getHeader(CorrelationIdFilter.HEADER_NAME)).thenReturn("mdc-test-id");

        FilterChain chain = mock(FilterChain.class);
        doAnswer(invocation -> {
            // Assert from inside the chain — this is the only point at
            // which MDC is guaranteed to still hold the value.
            assertThat(MDC.get(CorrelationIdFilter.MDC_KEY)).isEqualTo("mdc-test-id");
            return null;
        }).when(chain).doFilter(request, response);

        filter.doFilter(request, response, chain);

        assertThat(MDC.get(CorrelationIdFilter.MDC_KEY)).isNull();
    }

    @Test
    void clearsMdc_evenWhenTheChainThrows() {
        HttpServletRequest request = mock(HttpServletRequest.class);
        HttpServletResponse response = mock(HttpServletResponse.class);
        when(request.getHeader(CorrelationIdFilter.HEADER_NAME)).thenReturn("error-case-id");

        FilterChain chain = mock(FilterChain.class);
        try {
            doThrow(new RuntimeException("downstream failure")).when(chain).doFilter(request, response);
        } catch (Exception ignored) {
            // doThrow's checked-exception declaration, not a real call yet
        }

        org.junit.jupiter.api.Assertions.assertThrows(RuntimeException.class,
                () -> filter.doFilter(request, response, chain));

        assertThat(MDC.get(CorrelationIdFilter.MDC_KEY)).isNull();
    }
}
