/**
 * Cloudflare Worker to fetch the last 7 days of currency exchange rates.
 *
 * This worker responds to any incoming request by fetching historical data
 * from the Frankfurter API (https://api.frankfurter.dev). It automatically
 * calculates a time-aware date range to ensure 7 full days of data are returned,
 * accounting for the daily update time of the source API.
 */
export default {
  /**
   * The main fetch handler for the worker.
   * @param {Request} request - The incoming request object.
   * @param {object} env - The environment variables for the worker.
   * @param {object} ctx - The execution context of the request.
   * @returns {Promise<Response>} - The response object containing the currency data or an error.
   */
  async fetch(request, env, ctx) {
    try {
      // --- Configuration ---
      // Get parameters from the request URL's query string.
      // Example: https://your-worker.workers.dev?base=EUR&symbols=USD,MYR
      const { searchParams } = new URL(request.url);
      
      // It defaults to 'USD' if the 'base' parameter is not provided.
      const baseCurrency = searchParams.get('base') || 'USD';
      // The 'symbols' parameter is optional. If provided, it filters the results.
      const symbols = searchParams.get('symbols');


      // --- 1. Calculate the Time-Aware Date Range ---

      // Helper function to format a Date object into 'YYYY-MM-DD' string format.
      const formatDate = (date) => {
        return date.toISOString().split('T')[0];
      };

      // Get the current date and time in UTC. Cloudflare Workers run in UTC.
      const now = new Date();

      // The reference rates are updated around 16:00 CET.
      // CET is UTC+1, and CEST (Central European Summer Time) is UTC+2.
      // To be safe and account for summer time, we'll use 14:00 UTC as the cutoff.
      const cetUpdateHourUTC = 14;

      // Determine the correct end date based on the update time.
      const endDate = new Date(now);
      if (now.getUTCHours() < cetUpdateHourUTC) {
        // If the current time is before the daily update (e.g., 14:00 UTC / 16:00 CEST),
        // the latest complete data set is for yesterday.
        // So, we set the end date to yesterday.
        endDate.setDate(endDate.getDate() - 1);
      }
      // If it's after the update time, we can safely use today's date as the end date.

      // The start date is 7 days before our calculated, time-aware end date.
      // We subtract 6 to make the range inclusive of 7 days.
      const startDate = new Date(endDate);
      startDate.setDate(startDate.getDate() - 6);

      const formattedStartDate = formatDate(startDate);
      const formattedEndDate = formatDate(endDate);


      // --- 2. Construct the API URL and Fetch the History ---
      let apiUrl = `https://api.frankfurter.dev/v1/${formattedStartDate}..${formattedEndDate}?base=${baseCurrency}`;

      // If a 'symbols' parameter was provided, add it to the API URL.
      if (symbols) {
        apiUrl += `&symbols=${symbols}`;
      }

      // Log the generated URL and dates to the worker's console for debugging.
      console.log(`Fetching data from URL: ${apiUrl}`);
      console.log(`Date Range: ${formattedStartDate} to ${formattedEndDate}`);

      const historyResponse = await fetch(apiUrl);

      if (!historyResponse.ok) {
        const errorText = await historyResponse.text();
        // Forward the error from the history endpoint.
        return new Response(`Error from Frankfurter API history endpoint: ${errorText}`, {
          status: historyResponse.status,
          statusText: historyResponse.statusText,
        });
      }

      const historyData = await historyResponse.json();

      // --- 3. Return the Result ---
      const headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*', // Allow any domain to access this API
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
      };

      return new Response(JSON.stringify(historyData, null, 2), {
        headers: headers,
      });

    } catch (error) {
      // --- 4. Handle Errors ---
      console.error('Worker Error:', error);
      return new Response(error.message || 'An internal error occurred.', { status: 500 });
    }
  },
};
