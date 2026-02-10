# Trading Desk Project

## Application Development

### Client Portal API
**Understanding the Architecture** - *[website](https://interactivebrokers.github.io/cpwebapi/)*
Before we write any code, it is critical to understand that the Client Portal API (CP API) works a bit differently than a standard web API.
Because financial data is highly sensitive, IBKR requires a "bridge" between your Python script and their servers.
1. You (Python script in VSCode) send a request to your local machine (usually https://localhost:5000).
2. The Gateway (a small Java program running on your PC) receives this, handles the complex encryption/authentication, and forwards it to IBKR.
3. IBKR sends the data back to the Gateway, which passes it to your script.

So, we cannot just "query the API" directly from Python without this Gateway running.

**Next Steps**
1. The Setup (The Gateway) 🏗️ We can start by downloading and configuring the Client Portal Gateway. This is often the trickiest part because it involves handling a secure certificate (since it runs on https) and getting it to "talk" to your browser for the initial login.
2. The Data (The Endpoints) 📊 If you already have the Gateway running (or want to see the capabilities first), we can look at the specific API Endpoints (URLs) you will use to fetch Intraday PnL, Portfolio Risk, and specific Position data.
3. The Code (Python Structure) 🐍 We can sketch out the Python class structure in VSCode that will handle the requests, manage the session cookies (crucial for this API), and parse the JSON data into a clean "Risk Dashboard" format.

Steps to start the gataway:
1. In VSCode terminal go to: cd C:\ibkr_gateway
2. In VSCode terminal run: bin\run.bat root\conf.yaml
3. Go to: https://localhost:5000

### Trade history
This should reconcile into the NAV. But also it's purpouse is to track time value of my investment for risk management purpuses.
- When calculating ATR it matters on what date you started buying the instrument
- When assigning trailing or fixed stop, it matters what is your cost base

To do:
- [ ] Use **Conid** the specific instrument, **BUY** * **Price** * **Quantity** equals the *Cost Base*.
- [ ] When you want to sell something use FIFO or weighted average approach. Which one is better if you have a longer holding period and the market usually goes up?
- [ ] Use one method to fetch data - from IBKR and from yfinance
- [ ] Use one method to parse through the data that you've fetched
- [ ] Risk management - we need to keep certain datapoints in a database or a .json file. For example the first date of entry. Think about this..
- [ ] My father loves me.
- [ ] Simulate a purchase - provide ticker, entry date, entry price - it calculates ATR and provides a recommendation on how much you need to buy.

### Useful notes
VSCode plug-in - All you need to write Markdown (keyboard shortcuts, table of contents, auto preview and more)
Outline - uses the MD headers to create a table of content, you can see it at the bottom left corner of VSCode

### Code
```python
# A simple risk check
def check_limit(position_size):
    if position_size &gt; 100000:
        return &quot;Risk limit exceeded&quot;
    return &quot;Trade approved&quot;
```
### Dashboard
The information that is required in the dashboard is the following:
|Name|Ticker|Date|Qty|Entry|Price|P/L|CCY|Pct|AAGR|
|:---|:---|:---|:---|:---|:---|:---|:---|:---|:---|
|Name|Ticker|the first entry date|total quantity|avearge entry price|current price|unrealized profit|currency|unrealized profit %|average annualized growth rate|

note: [Difference btw. CAGR and AAGR](https://share.google/aimode/FEmi3YkShRDfJyib9)

### Issues
1. When calculating Trade History I use the Trade Confirmation Flex Query.
    - Quantity - Positive when you buy and negative when you sell -> the sum should equal **zero** if your entry and exit are in the time period that is being reported. Otherwise, you will have to go back to collect all entry points that will bring you to the full position size, which you sold in this period.

## Risk Management
### Stop-Loss Rules


