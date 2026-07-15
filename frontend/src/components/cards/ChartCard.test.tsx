import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChartCard } from './ChartCard';

describe('ChartCard accessibility', () => {
  it('associates the chart with its title, explanation, summary, and data table', () => {
    render(
      <ChartCard
        title="Daily spending"
        description="Day-by-day movement"
        chartSummary="Spending peaked on 12 July."
        context="Higher points represent higher daily spending."
        dataTable={
          <table>
            <tbody><tr><td>12 July</td><td>1000</td></tr></tbody>
          </table>
        }
      >
        <div role="img" aria-label="Daily spending chart" />
      </ChartCard>,
    );

    const figure = screen.getByRole('figure');
    expect(figure).toHaveAccessibleName('Daily spending');
    expect(figure).toHaveAccessibleDescription(/Day-by-day movement.*Spending peaked/);
    expect(screen.getByText('How to read')).toBeInTheDocument();
    expect(screen.getByText('View chart data')).toBeInTheDocument();
  });
});
