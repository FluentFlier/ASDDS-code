% Example configuration for the July 21-22, 2026 experiment.
% Edit or append entries in experiments to process other paired files.

matlabFolder = fileparts(mfilename('fullpath'));
repositoryRoot = fileparts(matlabFolder);
addpath(matlabFolder);

experiments(1).JetsonJson = fullfile(repositoryRoot, 'supplementary', 'july21_2026', ...
    'sleep_log_20260721 (1).json');
experiments(1).SwarmCsv = fullfile(repositoryRoot, ...
    'BRAID_24hr-260304-154142_JL-260721-180219_Cam1.avi_Tracker_DataComputer_2026-07-22 03-46-21.csv');
experiments(1).VideoStart = datetime(2026, 7, 21, 18, 2, 19);
experiments(1).FrameRate = 5;
experiments(1).Label = 'July 21-22, 2026';

outputDir = fullfile(repositoryRoot, 'outputs', 'jetson_swarmsight_matlab');
results = batch_plot_jetson_swarmsight(experiments, ...
    'OutputDir', outputDir, ...
    'OutputFormat', 'png', ...
    'Visible', 'on');

disp(struct2table([results.Metrics]'));
