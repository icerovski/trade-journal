# Trading Desk Project

## Application Development
### Trade history
This should reconcile into the NAV. But also it's purpouse is to track time value of my investment for risk management purpuses.
- When calculating ATR it matters on what date you started buying the instrument
- When assigning trailing or fixed stop, it matters what is your cost base

To do:
- [ ] Use **Conid** the specific instrument, **BUY** * **Price** * **Quantity** equals the *Cost Base*.
- [ ] When you want to sell something use FIFO or weighted average approach. Which one is better if you have a longer holding period and the market usually goes up?

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


