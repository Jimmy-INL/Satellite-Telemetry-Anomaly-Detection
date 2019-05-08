# Standard modules
import os
import datetime
from math import sqrt
import pandas as pd
from pandas import datetime
import numpy as np
from matplotlib import pyplot
from statsmodels.tsa.arima_model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX
from statsmodels.tsa.stattools import acf, pacf
from statsmodels.tsa.stattools import adfuller
from statsmodels.tsa.seasonal import seasonal_decompose
from statsmodels.tsa.arima_model import ARIMAResults
from sklearn.metrics import mean_squared_error

# Custom modules
from grid_search_hyperparameters import grid_search_arima_params
from grid_search_hyperparameters import grid_search_sarima_params
import nonparametric_dynamic_thresholding as ndt

__author__ = 'Shawn Polson'
__contact__ = 'shawn.polson@colorado.edu'


def model_with_arima(ts, train_size, order, seasonal_order=(), seasonal_freq=None, trend=None,
                                grid_search=False, path_to_model=None, verbose=False, ds_name='DS', var_name='Value'):
    """Detect outliers in the time series data by comparing points against an ARIMA forecast.

       Inputs:
           ts [pd Series]:     A pandas Series with a DatetimeIndex and a column for numerical values.
           train_size [float]: The percentage of data to use for training, as a float (e.g., 0.66).
           order [tuple]:      The order hyperparameters (p,d,q) for this ARIMA model.


       Optional Inputs:
           seasonal_order [tuple]: The seasonal order hyperparameters (P,D,Q) for this SARIMA model. When specifying these, 'seasonal_freq' must also be given.
           seasonal_freq [int]:    The freq hyperparameter for this SARIMA model, i.e., the number of samples that make up one seasonal cycle.
           trend [str]:            The trend hyperparameter for an SARIMA model.
           grid_search [bool]:     When True, perform a grid search to set values for the 'order' and 'seasonal order' hyperparameters.
                                   Note this overrides any given (p,d,q)(P,D,Q) hyperparameter values. Default is False.
           path_to_model [str]:    Path to a *.pkl file of a trained (S)ARIMA model. When set, no training will be done because that model will be used.
           verbose [bool]:         When True, show ACF and PACF plots before grid searching, plot residual training errors after fitting the model,
                                   and print predicted v. expected values during outlier detection. TODO: mention plot w/ forecast & outliers once it's under an "if verbose"
           var_name [str]:         The name of the dependent variable in the time series.
                                   Default is 'Value'.


       Outputs:
           time_series_with_outliers [pd DataFrame]: A pandas DataFrame with a DatetimeIndex, a columns for numerical values, and an Outlier column (True or False).

       Optional Outputs:
           None

       Example:
           time_series_with_outliers = model_with_arima(time_series, train_size=0.8, order=(12,0,0),
                                                                             seasonal_order=(0,1,0), seasonal_freq=365,
                                                                             verbose=False)
    """

    # Finalize ARIMA/SARIMA hyperparameters
    if grid_search and path_to_model is not None:
        raise ValueError('\'grid_search\' should be False when specifying a path to a pre-trained ARIMA model.')

    if (seasonal_freq is not None) and (len(seasonal_order) == 3) and (grid_search is False):
        seasonal_order = seasonal_order + (seasonal_freq,)  # (P,D,Q,freq)
    elif (seasonal_freq is not None) and (len(seasonal_order) != 3) and (grid_search is False):
        raise ValueError('\'seasonal_order\' must be a tuple of 3 integers when specifying a seasonal frequency and not grid searching.')
    elif (seasonal_freq is None) and (len(seasonal_order) == 3) and (grid_search is False):
        raise ValueError('\'seasonal_freq\' must be given when specifying a seasonal order and not grid searching.')

    if grid_search:
        if verbose:
            lag_acf = acf(ts, nlags=20)
            lag_pacf = pacf(ts, nlags=20, method='ols')
            pyplot.show()
        if seasonal_freq is None:  # ARIMA grid search
            print('No seasonal frequency was given, so grid searching ARIMA(p,d,q) hyperparameters.')
            order = grid_search_arima_params(ts)
            print('Grid search found hyperparameters: ' + str(order) + '\n')
        else:  # SARIMA grid search
            print('Seasonal frequency was given, so grid searching ARIMA(p,d,q)(P,D,Q) hyperparameters.')
            order, seasonal_order, trend = grid_search_sarima_params(ts, seasonal_freq)
            print('Grid search found hyperparameters: ' + str(order) + str(seasonal_order) + '\n')

    # Train or load ARIMA/SARIMA model
    X = ts
    split = int(len(X) * train_size)
    train, test = X[0:split], X[split:len(X)]
    threshold = float(train.values.std(ddof=0)) * 2.0  # TODO: 2stds; finalize/decide std scheme (pass it in?)

    if len(seasonal_order) < 4:
        trained_model = ARIMA(train, order=order)
    else:
        # TODO: consider enforce_stationarity=False and enforce_invertibility=False, unless that prevents from detecting 2 DSs not right for ARIMA
        trained_model = SARIMAX(train, order=order, seasonal_order=seasonal_order, trend=trend)

    if path_to_model is not None:
        # load pre-trained model
        print('Loading model: ' + path_to_model)
        trained_model_fit = ARIMAResults.load(path_to_model)
    else:
        current_time = str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print('Before fitting: ' + current_time + '\n')

        trained_model_fit = trained_model.fit(disp=1)

        current_time = str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print('After fitting: ' + current_time + '\n')
        # save the just-trained model
        try:
            current_time = str(datetime.now().strftime("%Y-%m-%dT%H-%M-%S"))
            filename = 'SARIMA_' + var_name + '_' + train_size + '_' + str(order) + '_' + str(seasonal_order) + '_' + current_time + '.pkl'
            model_dir = 'Models/'
            if not os.path.exists(model_dir):
                os.makedirs(model_dir)
            filename = model_dir + filename
            trained_model_fit.save(filename)
        except Exception as e:
            print('Saving model failed:')
            print(e)

    print(trained_model_fit.summary())

    if verbose:
        # plot residual errors
        residuals = pd.DataFrame(trained_model_fit.resid)
        residuals.plot(title='Training Model Fit Residual Errors')
        pyplot.show()
        residuals.plot(kind='kde', title='Training Model Fit Residual Error Density')
        pyplot.show()
        print('\n')

    # Forecast with the trained ARIMA/SARIMA model
    predictions = trained_model_fit.predict(start=1, end=len(X)-1, typ='levels')
    predict_index = pd.Index(X.index[1:len(X)])
    predictions_with_dates = pd.Series(predictions.values, index=predict_index)
    errors = pd.Series()


    try:
        model_error = sqrt(mean_squared_error(X[1:len(X)], predictions_with_dates))
        print('RMSE: %.3f' % model_error)
        if len(test) > 0:
            test_error = mean_squared_error(test, predictions_with_dates[test.index[0]:test.index[-1]])
            print('Test MSE: %.3f' % test_error)
    except Exception as e:
        print('Forecast error calculation failed:')
        print(e)

    # Plot the forecast and outliers  # TODO: save plot and dataframe
    if len(seasonal_order) < 4:  # ARIMA title
        title_text = ds_name + ' with ' + str(order) + ' ARIMA Forecast'
    else:  # SARIMA title
        title_text = ds_name + ' with ' + str(order) + '_' + str(seasonal_order) + '_' + str(trend) + ' ARIMA Forecast'
    X.plot(color='#192C87', title=title_text, label=var_name)
    if len(test) > 0:
        test.plot(color='purple', label='Test Data')
    predictions_with_dates.plot(color='#0CCADC', label='ARIMA Forecast')
    pyplot.legend(loc='best')

    if train_size == 1:
        plot_filename = ds_name + '_with_arima_full.png'
    elif train_size == 0.5:
        plot_filename = ds_name + '_with_arima_half.png'
    else:
        plot_filename = ds_name + '_with_arima_' + str(train_size) + '.png'
    plot_path = './save/datasets/' + ds_name + '/arima/plots/' + str(int(train_size*100)) + ' percent/'
    if not os.path.exists(plot_path):
        os.makedirs(plot_path)
    pyplot.savefig(plot_path + plot_filename, dpi=500)

    pyplot.show()

    return predictions_with_dates  # TODO: return combined with ts in dataframe