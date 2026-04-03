import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.statespace.sarimax import SARIMAX
from sklearn.linear_model import LinearRegression


def create_model(levels, years_to_predict):

    months_to_predict = years_to_predict * 12

    model = SARIMAX(levels,
                    order=(1,1,1),
                    seasonal_order=(1,1,1,12))

    results = model.fit()

    prediction = results.forecast(steps=months_to_predict)

    return prediction


def compute_trend(levels):

    X = np.arange(len(levels)).reshape(-1,1)

    model = LinearRegression()
    model.fit(X, levels)

    trend = model.predict(X)

    return trend


def compute_moving_average(levels):

    moving_avg = pd.Series(levels).rolling(window=12).mean()

    return moving_avg


def create_graph_with_recorded_data(dates, levels, prediction):

    plt.figure(figsize=(14,6))

    plt.plot(dates, levels, color='blue', label="Données observées")

    trend = compute_trend(levels)
    plt.plot(dates, trend, color='green', linewidth=2, label="Tendance")

    moving_avg = compute_moving_average(levels)
    plt.plot(dates, moving_avg, color='purple', linewidth=2, label="Moyenne mobile (12 mois)")

    last_date = dates.iloc[-1]

    future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1),
                                 periods=len(prediction),
                                 freq='MS')

    plt.plot(future_dates, prediction, color='red', linestyle='--', label="Prédiction")

    plt.title("Chronique piézométrique avec tendance et prédiction")
    plt.xlabel("Date")
    plt.ylabel("Niveau piézométrique (m NGF)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


def read_chroniquePiezo(years_to_predict):

    df = pd.read_excel("C:/Users/bruno.DESKTOP-I2NE6NI/OneDrive/Bureau/Projet_Courbes_piezo/chro_piezo_1995_2024_mensuelle.xlsx")

    dates = pd.to_datetime(df.iloc[:,0])
    levels = df.iloc[:,1].astype(float)

    prediction = create_model(levels, years_to_predict)

    create_graph_with_recorded_data(dates, levels, prediction)

def create_temporal_histogram(dates, levels, prediction):

    last_date = dates.iloc[-1]

    future_dates = pd.date_range(start=last_date + pd.DateOffset(months=1),
                                 periods=len(prediction),
                                 freq='MS')

    plt.figure(figsize=(14,6))

    # barres historiques
    plt.bar(dates,
            levels,
            color='blue',
            label="Données historiques",
            width=20)

    # barres prédites
    plt.bar(future_dates,
            prediction,
            color='red',
            label="Prédictions",
            width=20)

    plt.title("Chronique piézométrique (diagramme en barres)")
    plt.xlabel("Date")
    plt.ylabel("Niveau piézométrique (m NGF)")
    plt.legend()
    plt.grid(True)

    plt.tight_layout()
    plt.show()



if __name__ == '__main__':
    read_chroniquePiezo(5)