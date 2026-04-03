import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.tsa.statespace.sarimax import SARIMAX
from sklearn.linear_model import LinearRegression


# ---------------------------
# MODÈLE SARIMA
# ---------------------------
def create_model(levels, years_to_predict):

    months_to_predict = years_to_predict * 12

    model = SARIMAX(levels,
                    order=(1,1,1),
                    seasonal_order=(1,1,1,12))

    results = model.fit()

    prediction = results.forecast(steps=months_to_predict)

    return prediction


# ---------------------------
# MODÈLE HYDROGÉO
# ---------------------------
def apply_hydro_model(prediction,
                      storage=0.01,
                      recharge_factor=1.0,
                      recharge_maitrisee=0.0,
                      pumping=0.0,
                      hydro_strength=0.2):

    adjusted = prediction.to_numpy().copy()

    for i in range(len(adjusted)):

        #recharge = recharge_factor * np.sin(2*np.pi*i/12)
        recharge_naturelle = recharge_factor  * np.sin(2*np.pi*i/12)
        recharge_totale = recharge_naturelle + recharge_maitrisee

        #hydro_effect = (recharge - pumping) / storage
        hydro_effect = (recharge_totale - pumping)/storage

        adjusted[i] = adjusted[i] + hydro_effect * hydro_strength

    return pd.Series(adjusted, index=prediction.index)


# ---------------------------
# VALIDATION DU MODÈLE
# ---------------------------
def validate_model(levels, dates, years_to_validate,
                   storage, recharge_factor, pumping, hydro_strength):

    months = years_to_validate * 12

    train = levels[:-months]
    test = levels[-months:]
    test_dates = dates[-months:]

    model = SARIMAX(train,
                    order=(1,1,1),
                    seasonal_order=(1,1,1,12))

    results = model.fit()

    prediction = results.forecast(steps=months)

    prediction_adjusted = apply_hydro_model(prediction,
                                            storage,
                                            recharge_factor,
                                            pumping,
                                            hydro_strength)

    # score RMSE → %
    rmse = np.sqrt(np.mean((test - prediction_adjusted)**2))
    score = 100 * (1 - rmse / np.std(test))

    return test, prediction_adjusted, test_dates, score


# ---------------------------
# TENDANCE
# ---------------------------
def compute_trend(levels):

    X = np.arange(len(levels)).reshape(-1,1)

    model = LinearRegression()
    model.fit(X, levels)

    return model.predict(X)


# ---------------------------
# MOYENNE MOBILE
# ---------------------------
def compute_moving_average(levels):

    return pd.Series(levels).rolling(window=12).mean()


# ---------------------------
# GRAPHIQUE PRINCIPAL
# ---------------------------
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

    plt.title("Chronique piézométrique avec prédiction")
    plt.xlabel("Date")
    plt.ylabel("Niveau piézométrique (m NGF)")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


# ---------------------------
# GRAPHIQUE VALIDATION
# ---------------------------
def plot_validation(test_dates, test, prediction):

    plt.figure(figsize=(14,6))

    plt.plot(test_dates, test, label="Données réelles", color='blue')
    plt.plot(test_dates, prediction, label="Fit modèle", color='orange')

    plt.title("Validation du modèle sur 5 ans")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    plt.show()


# ---------------------------
# FONCTION PRINCIPALE
# ---------------------------
def read_chroniquePiezo(years_to_predict,
                        storage=0.01,
                        recharge_factor=1.0,
                        recharge_maitrisee=0.0,
                        pumping=0.0,
                        hydro_strength=0.2):

    df = pd.read_excel("C:/Users/bruno.DESKTOP-I2NE6NI/OneDrive/Bureau/Projet_Courbes_piezo/chro_piezo_1995_2024_mensuelle.xlsx")

    dates = pd.to_datetime(df.iloc[:,0])
    levels = df.iloc[:,1].astype(float)

    # ---------------------------
    # VALIDATION (5 ans passés)
    # ---------------------------
    test, fit_prediction, test_dates, score = validate_model(
        levels,
        dates,
        years_to_validate=5,
        storage=storage,
        recharge_factor=recharge_factor,
        pumping=pumping,
        hydro_strength=hydro_strength
    )

    print(f"Score du modèle : {score:.2f} %")

    plot_validation(test_dates, test, fit_prediction)

    # ---------------------------
    # PRÉDICTION FUTURE
    # ---------------------------
    prediction = create_model(levels, years_to_predict)

    prediction_adjusted = apply_hydro_model(prediction,
                                            storage,
                                            recharge_factor,
                                            recharge_maitrisee,
                                            pumping,
                                            hydro_strength)

    create_graph_with_recorded_data(dates, levels, prediction_adjusted)

# ---------------------------
# EXECUTION
# ---------------------------
if __name__ == '__main__':

    read_chroniquePiezo(
        #Durée de la prédiction => longueur de la projection SARIMA
        years_to_predict=5,

        #Coefficient d’emmagasinement de la nappe => représente la capacité de la nappe à stocker de l’eau
        #faible (0.001 – 0.01) → nappe captive (peu compressible)
        #moyen (0.01 – 0.1) → nappe semi-captive
        #élevé (>0.1) → nappe libre très réactive
        storage=0.05,

        #Intensité de la recharge => liée à la pluie infiltrée, ruissellement, etc.
        #0 → aucune recharge
        #faible(0.01–0.1) → climat sec ou infiltration faible
        #élevé( > 0.1) → recharge importante(climat humide)
        recharge_factor=0.055,

        #0.0 aucune recharge artificielle
        #0.025 injection modérée
        #0.05 injection forte
        #0.1 recharge très importante
        recharge_maitrisee = 0.0,

        #représente les prélèvements humains dans la nappe
        #0 → pas de pompage
        pumping=0.0,

        #Intensité du couplage hydrogéologique => il contrôle combien ton modèle hydrogéo influence la prédiction SARIMA
        #0 → aucun effet hydrogéo(SARIMA pur)
        #0.1–0.3 → influence légère(réaliste)
        #0.5 → forte dominance physique(risque de dérive)
        hydro_strength=0.2
    )