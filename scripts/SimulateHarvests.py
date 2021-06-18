from .TelegramBot import sendMessage
import brownie
from brownie import interface, accounts, web3, chain
from brownie.network.event import _decode_logs
from babel.dates import format_timedelta
from datetime import datetime
import pandas as pd

def main():
    daddy = accounts.at(web3.ens.resolve("ychad.eth"), force=True)
    strategiesHelperAddress = "0xae813841436fe29b95a14AC701AFb1502C4CB789"
    oracleAddress = "0x83d95e0D5f402511dB06817Aff3f9eA88224B030"
    oracle = interface.IOracle(oracleAddress)
    strategiesHelper = interface.IStrategiesHelper(strategiesHelperAddress)
    strategiesAddresses = strategiesHelper.assetsStrategiesAddresses()
    for strategyAddress in strategiesAddresses:
        strategy = interface.IStrategy(strategyAddress)
        strategyName = strategy.name()
        strategyApiVersion = strategy.apiVersion()
        strategist = strategy.strategist()
        vaultAddress = strategy.vault()
        vault = interface.IVault032(vaultAddress)
        vaultName = vault.name()
        tokenAddress = vault.token()
        token = interface.IERC20(tokenAddress)
        tokenSymbol = token.symbol()
        tokenDecimals = token.decimals()
        vaultVersion = int(vault.apiVersion().replace(".", ""))
        if vaultVersion == 30:
            vault = interface.IVault030(vaultAddress)
        if vaultVersion == 31:
            vault = interface.IVault031(vaultAddress)

        # State before harvest
        strategyStatistics = vault.strategies(strategy)
        debtBeforeHarvest = strategyStatistics.dict()["totalDebt"]
        gainBeforeHarvest = strategyStatistics.dict()["totalGain"]
        lossBeforeHarvest = strategyStatistics.dict()["totalLoss"]
        reportBeforeHarvest = strategyStatistics.dict()["lastReport"]
        debtOutstandingBeforeHarvest = vault.debtOutstanding(strategyAddress)
        pricePerShareOriginal = vault.pricePerShare()
        assetsBeforeHarvest = vault.totalAssets()
        actualRatio = debtBeforeHarvest / (assetsBeforeHarvest + 1)

        try:
            harvestTriggerReady = strategy.harvestTrigger(2_000_000 * 300 * 1e9)
        except:
            harvestTriggerReady = "Broken"

        # Perform harvest and wait
        hoursToWait = 10
        try:
            strategy.harvest({"from": daddy})
        except:
            print("Can't harvest", strategyAddress)
            chain.reset()
            continue
        chain.sleep(60 * 60 * hoursToWait)
        chain.mine(1)

        # State after harvest
        strategyStatistics = vault.strategies(strategy)
        pricePerShareAfterTenHours = vault.pricePerShare()
        debtAfterHarvest = strategyStatistics.dict()["totalDebt"]
        gainAfterHarvest = strategyStatistics.dict()["totalGain"]
        lossAfterHarvest = strategyStatistics.dict()["totalLoss"]
        reportAfterHarvest = strategyStatistics.dict()["lastReport"]
        debtOutstandingAfterHarvest = vault.debtOutstanding(strategyAddress)
        assetsAfterHarvest = vault.totalAssets()

        # State delta
        debtDelta = (debtAfterHarvest / 10**tokenDecimals) - (debtBeforeHarvest / 10**tokenDecimals)
        gainDelta = (gainAfterHarvest / 10**tokenDecimals) - (gainBeforeHarvest / 10**tokenDecimals)
        lossDelta = (lossAfterHarvest / 10**tokenDecimals) - (lossBeforeHarvest / 10**tokenDecimals)
        debtOutstandingDelta = (
            (debtOutstandingAfterHarvest / 10**tokenDecimals) - (debtOutstandingBeforeHarvest / 10**tokenDecimals)
        )
        reportDelta = reportAfterHarvest - reportBeforeHarvest
        assetsDelta = assetsAfterHarvest - assetsBeforeHarvest

        # Calculate and format results
        percent = 0
        if debtBeforeHarvest > 0:
            if lossDelta > gainDelta:
                percent = -1 * lossDelta / debtBeforeHarvest
            else:
                percent = gainDelta / debtBeforeHarvest
        estimatedApr = percent * 3.154e7 / reportDelta
        lastHarvest = format_timedelta(reportDelta, locale="en_US") + " ago"
        desiredRatio = "{:.4%}".format(strategyStatistics.dict()["debtRatio"] / 10000)
        actualRatio = "{:.4%}".format(actualRatio)
        estimatedApr = "{:.4%}".format(estimatedApr)
        ppsPercentChange = (
            ((pricePerShareAfterTenHours - pricePerShareOriginal))
            / pricePerShareOriginal
        ) * 100

        profitInUsd = (
            f"${oracle.getNormalizedValueUsdc(tokenAddress, gainDelta) / 10 ** 6:,.2f}"
        )
        lossInUsd = (
            f"${oracle.getNormalizedValueUsdc(tokenAddress, lossDelta) / 10 ** 6:,.2f}"
        )
        profitInUnderlying = f"{gainDelta} {tokenSymbol}"

        sharePriceOk = (
            ppsPercentChange >= 0
            and ppsPercentChange < 1
            and pricePerShareAfterTenHours >= 1 ** tokenDecimals
        )
        profitAndLossOk = gainDelta >= 0 and lossDelta == 0
        everythingOk = sharePriceOk and profitAndLossOk

        def boolDescription(bool):
            return "PASSED" if bool else "FAILED"

        if not everythingOk:
            df = pd.DataFrame(index=[''])
            df["ALERT 🚨"] = datetime.now().isoformat()
            df[" "] = f""
            df["----- STRATEGY DESCRIPTION-------"] = f""
            df[f"{strategyName}"] = ""
            df["Strategy address"] = f"{strategyAddress}"
            df["Token address"] = f"{tokenAddress}"
            df["Vault Address"] = f"{vaultAddress}"
            df["Strategist Address"] = f"{strategist}"
            df["Vault Name"] = f"{vaultName}"
            df["Strategy API Version"] = f"{strategyApiVersion}"
            df["Total Gain before"] = f"{gainBeforeHarvest / 10**tokenDecimals}"
            df["Total Loss before"] = f"{lossBeforeHarvest / 10**tokenDecimals}"
            df[" "] = f""
            df["----- HARVEST SIMULATION DATA-------"] = f""
            df["Last harvest"] = f"{lastHarvest}"
            df["Profit"] = f"{profitInUnderlying}"
            df["Profit in USD"] = f"{profitInUsd}"
            df["Loss"] = f"{lossDelta}"
            df["Loss in USD"] = f"{lossInUsd}"
            df["Estimated APR"] = f"{estimatedApr}"
            df["PPS percent change"] = f"{ppsPercentChange}"
            df["Previous PPS"] = f"{pricePerShareOriginal / 10**tokenDecimals}"
            df["New PPS"] = f"{pricePerShareAfterTenHours / 10**tokenDecimals}"
            df["Target ratio"] = f"{desiredRatio}"
            df["Actual ratio"] = f"{actualRatio}"
            df[" "] = f""
            df["----- HEALTH CHECKS-------"] = f""
            df["Harvest trigger ready"] = f"{boolDescription(harvestTriggerReady)}"
            df["Share price change"] = f"{boolDescription(sharePriceOk)}"
            df["Profit/loss check"] = f"{boolDescription(profitAndLossOk)}"
            sendMessage(df.T.to_string())

        chain.reset()
