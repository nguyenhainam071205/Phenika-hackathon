import React, { useState, useEffect, useMemo } from 'react';
import classnames from 'classnames';
import PropTypes from 'prop-types';
import { Link, useNavigate } from 'react-router-dom';
import moment from 'moment';
import qs from 'query-string';
import isEqual from 'lodash.isequal';
import { useTranslation } from 'react-i18next';
//
import filtersMeta from './filtersMeta.js';
import { useAppConfig } from '@state';
import { useDebounce, useSearchParams } from '../../hooks';
import { utils, Types as coreTypes } from '@ohif/core';

import {
  StudyListExpandedRow,
  EmptyStudies,
  StudyListTable,
  StudyListPagination,
  StudyListFilter,
  Button,
  ButtonEnums,
} from '@ohif/ui';

import {
  Header,
  Icons,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  Clipboard,
  useModal,
  useSessionStorage,
  Onboarding,
  ScrollArea,
  InvestigationalUseDialog,
} from '@ohif/ui-next';

import { Types } from '@ohif/ui';

import { preserveQueryParameters, preserveQueryStrings } from '../../utils/preserveQueryParameters';

const PatientInfoVisibility = Types.PatientInfoVisibility;

const { sortBySeriesDate } = utils;

const seriesInStudiesMap = new Map();

function normalizeDicomDateInput(dateValue) {
  if (!dateValue) {
    return '';
  }

  const digits = String(dateValue).replace(/[^0-9]/g, '');
  if (digits.length !== 8) {
    return '';
  }

  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`;
}

function toDicomDate(dateInputValue) {
  if (!dateInputValue) {
    return '';
  }

  return String(dateInputValue).replace(/[^0-9]/g, '').slice(0, 8);
}

function PatientInfoEditForm({ initialValues, onSave, onCancel }) {
  const [formValues, setFormValues] = useState(initialValues);
  const [isSaving, setIsSaving] = useState(false);

  const setField = (key, value) => {
    setFormValues(prev => ({
      ...prev,
      [key]: value,
    }));
  };

  const handleSave = async () => {
    if (isSaving) {
      console.warn('[PatientInfoEditForm] Save already in progress');
      return;
    }
    
    setIsSaving(true);
    try {
      await onSave({
        patientId: (formValues.patientId || '').trim(),
        patientName: (formValues.patientName || '').trim(),
        patientBirthDate: toDicomDate(formValues.patientBirthDate),
        patientSex: (formValues.patientSex || '').trim(),
        studyDescription: (formValues.studyDescription || '').trim(),
      });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-3 p-1">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="text-sm text-white">Mã bệnh nhân</span>
          <input
            className="border-input bg-background text-foreground rounded border px-3 py-2"
            value={formValues.patientId}
            onChange={event => setField('patientId', event.target.value)}
            disabled={isSaving}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm text-white">Tên bệnh nhân</span>
          <input
            className="border-input bg-background text-foreground rounded border px-3 py-2"
            value={formValues.patientName}
            onChange={event => setField('patientName', event.target.value)}
            disabled={isSaving}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm text-white">Ngày sinh</span>
          <input
            type="date"
            className="border-input bg-background text-foreground rounded border px-3 py-2"
            value={formValues.patientBirthDate}
            onChange={event => setField('patientBirthDate', event.target.value)}
            disabled={isSaving}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-sm text-white">Giới tính</span>
          <select
            className="border-input bg-background text-foreground rounded border px-3 py-2"
            value={formValues.patientSex}
            onChange={event => setField('patientSex', event.target.value)}
            disabled={isSaving}
          >
            <option value="">Chọn giới tính</option>
            <option value="M">Nam</option>
            <option value="F">Nữ</option>
            <option value="O">Khác</option>
          </select>
        </label>
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-sm text-white">Mô tả phiên chụp</span>
        <textarea
          className="border-input bg-background text-foreground min-h-24 rounded border px-3 py-2"
          value={formValues.studyDescription}
          onChange={event => setField('studyDescription', event.target.value)}
          disabled={isSaving}
        />
      </label>
      <div className="mt-2 flex justify-end gap-2">
        <Button
          type={ButtonEnums.type.secondary}
          size={ButtonEnums.size.smallTall}
          onClick={onCancel}
          disabled={isSaving}
        >
          Hủy
        </Button>
        <Button
          type={ButtonEnums.type.primary}
          size={ButtonEnums.size.smallTall}
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? 'Đang lưu...' : 'Lưu thông tin'}
        </Button>
      </div>
    </div>
  );
}

/**
 * TODO:
 * - debounce `setFilterValues` (150ms?)
 */
function WorkList({
  data: studies,
  dataTotal: studiesTotal,
  isLoadingData,
  dataSource,
  hotkeysManager,
  dataPath,
  onRefresh,
  servicesManager,
}: withAppTypes) {
  const { show, hide } = useModal();
  const { t } = useTranslation();
  // ~ Modes
  const [appConfig] = useAppConfig();
  // ~ Filters
  const searchParams = useSearchParams();
  const navigate = useNavigate();
  const STUDIES_LIMIT = 101;
  const queryFilterValues = _getQueryFilterValues(searchParams);
  const [sessionQueryFilterValues, updateSessionQueryFilterValues] = useSessionStorage({
    key: 'queryFilterValues',
    defaultValue: queryFilterValues,
    // ToDo: useSessionStorage currently uses an unload listener to clear the filters from session storage
    // so on systems that do not support unload events a user will NOT be able to alter any existing filter
    // in the URL, load the page and have it apply.
    clearOnUnload: true,
  });
  const [filterValues, _setFilterValues] = useState({
    ...defaultFilterValues,
    ...sessionQueryFilterValues,
  });

  const debouncedFilterValues = useDebounce(filterValues, 200);
  const { resultsPerPage, pageNumber, sortBy, sortDirection } = filterValues;

  /*
   * The default sort value keep the filters synchronized with runtime conditional sorting
   * Only applied if no other sorting is specified and there are less than 101 studies
   */

  const canSort = studiesTotal < STUDIES_LIMIT;
  const shouldUseDefaultSort = sortBy === '' || !sortBy;
  const sortModifier = sortDirection === 'descending' ? 1 : -1;
  const defaultSortValues =
    shouldUseDefaultSort && canSort ? { sortBy: 'studyDate', sortDirection: 'ascending' } : {};
  const { customizationService } = servicesManager.services;

  const sortedStudies = useMemo(() => {
    if (!canSort) {
      return studies;
    }

    return [...studies].sort((s1, s2) => {
      if (shouldUseDefaultSort) {
        const ascendingSortModifier = -1;
        return _sortStringDates(s1, s2, ascendingSortModifier);
      }

      const s1Prop = s1[sortBy];
      const s2Prop = s2[sortBy];

      if (typeof s1Prop === 'string' && typeof s2Prop === 'string') {
        return s1Prop.localeCompare(s2Prop) * sortModifier;
      } else if (typeof s1Prop === 'number' && typeof s2Prop === 'number') {
        return (s1Prop > s2Prop ? 1 : -1) * sortModifier;
      } else if (!s1Prop && s2Prop) {
        return -1 * sortModifier;
      } else if (!s2Prop && s1Prop) {
        return 1 * sortModifier;
      } else if (sortBy === 'studyDate') {
        return _sortStringDates(s1, s2, sortModifier);
      }

      return 0;
    });
  }, [canSort, studies, shouldUseDefaultSort, sortBy, sortModifier]);

  // ~ Rows & Studies
  const [expandedRows, setExpandedRows] = useState([]);
  const [studiesWithSeriesData, setStudiesWithSeriesData] = useState([]);
  const [deletingStudyUid, setDeletingStudyUid] = useState<string | null>(null);
  const [savingStudyUid, setSavingStudyUid] = useState<string | null>(null);
  const [editedStudyMap, setEditedStudyMap] = useState({});
  const numOfStudies = studiesTotal;
  const querying = useMemo(() => {
    return isLoadingData || expandedRows.length > 0;
  }, [isLoadingData, expandedRows]);

  const setFilterValues = val => {
    if (filterValues.pageNumber === val.pageNumber) {
      val.pageNumber = 1;
    }
    _setFilterValues(val);
    updateSessionQueryFilterValues(val);
    setExpandedRows([]);
  };

  const onPageNumberChange = newPageNumber => {
    const oldPageNumber = filterValues.pageNumber;
    const rollingPageNumberMod = Math.floor(101 / filterValues.resultsPerPage);
    const rollingPageNumber = oldPageNumber % rollingPageNumberMod;
    const isNextPage = newPageNumber > oldPageNumber;
    const hasNextPage = Math.max(rollingPageNumber, 1) * resultsPerPage < numOfStudies;

    if (isNextPage && !hasNextPage) {
      return;
    }

    setFilterValues({ ...filterValues, pageNumber: newPageNumber });
  };

  const onResultsPerPageChange = newResultsPerPage => {
    setFilterValues({
      ...filterValues,
      pageNumber: 1,
      resultsPerPage: Number(newResultsPerPage),
    });
  };

  // Set body style
  useEffect(() => {
    document.body.classList.add('bg-black');
    return () => {
      document.body.classList.remove('bg-black');
    };
  }, []);

  // Sync URL query parameters with filters
  useEffect(() => {
    if (!debouncedFilterValues) {
      return;
    }

    const queryString = {};
    Object.keys(defaultFilterValues).forEach(key => {
      const defaultValue = defaultFilterValues[key];
      const currValue = debouncedFilterValues[key];

      // TODO: nesting/recursion?
      if (key === 'studyDate') {
        if (currValue.startDate && defaultValue.startDate !== currValue.startDate) {
          queryString.startDate = currValue.startDate;
        }
        if (currValue.endDate && defaultValue.endDate !== currValue.endDate) {
          queryString.endDate = currValue.endDate;
        }
      } else if (key === 'modalities' && currValue.length) {
        queryString.modalities = currValue.join(',');
      } else if (currValue !== defaultValue) {
        queryString[key] = currValue;
      }
    });

    preserveQueryStrings(queryString);

    const search = qs.stringify(queryString, {
      skipNull: true,
      skipEmptyString: true,
    });
    navigate({
      pathname: '/',
      search: search ? `?${search}` : undefined,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedFilterValues]);

  // Query for series information
  useEffect(() => {
    const fetchSeries = async studyInstanceUid => {
      try {
        const series = await dataSource.query.series.search(studyInstanceUid);
        seriesInStudiesMap.set(studyInstanceUid, sortBySeriesDate(series));
        setStudiesWithSeriesData([...studiesWithSeriesData, studyInstanceUid]);
      } catch (ex) {
        // TODO: UI Notification Service
        console.warn(ex);
      }
    };

    // TODO: WHY WOULD YOU USE AN INDEX OF 1?!
    // Note: expanded rows index begins at 1
    for (let z = 0; z < expandedRows.length; z++) {
      const expandedRowIndex = expandedRows[z] - 1;
      
      if (!sortedStudies || !sortedStudies[expandedRowIndex]) {
        console.warn(`[WorkList] Study not found at index ${expandedRowIndex}`);
        continue;
      }
      
      const studyInstanceUid = sortedStudies[expandedRowIndex].studyInstanceUid;

      if (studiesWithSeriesData.includes(studyInstanceUid)) {
        continue;
      }

      fetchSeries(studyInstanceUid);
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedRows, studies]);

  const isFiltering = (filterValues, defaultFilterValues) => {
    return !isEqual(filterValues, defaultFilterValues);
  };

  const rollingPageNumberMod = Math.floor(101 / resultsPerPage);
  const rollingPageNumber = (pageNumber - 1) % rollingPageNumberMod;
  const offset = resultsPerPage * rollingPageNumber;
  const offsetAndTake = offset + resultsPerPage;
  const handleDeleteStudy = async (studyInstanceUid: string) => {
    if (!dataSource?.store?.deleteStudy) {
      show({
        title: 'Delete Study Not Available',
        content: () => (
          <div className="text-foreground">
            <p>This data source does not support deleting studies.</p>
          </div>
        ),
      });
      return;
    }

    const confirmed = window.confirm(
      `Delete this study from server?\n\nStudy UID:\n${studyInstanceUid}`
    );

    if (!confirmed) {
      return;
    }

    try {
      setDeletingStudyUid(studyInstanceUid);
      await dataSource.store.deleteStudy(studyInstanceUid);
      seriesInStudiesMap.delete(studyInstanceUid);
      setExpandedRows([]);
      onRefresh();
    } catch (error) {
      const message = error?.message || 'Failed to delete study.';
      show({
        title: 'Delete Study Failed',
        content: () => (
          <div className="text-foreground">
            <p className="text-red-600">{message}</p>
          </div>
        ),
      });
    } finally {
      setDeletingStudyUid(null);
    }
  };

  const handleOpenEditPatientModal = study => {
    if (!study || !study.studyInstanceUid) {
      console.error('[WorkList] Edit modal called with undefined study or missing studyInstanceUid:', study);
      return;
    }

    // Capture studyInstanceUid to avoid closure issues
    const capturedStudyInstanceUid = study.studyInstanceUid;

    const initialValues = {
      patientId: study.mrn || '',
      patientName: study.patientName || '',
      patientBirthDate: normalizeDicomDateInput(study.patientBirthDate),
      patientSex: study.patientSex || '',
      studyDescription: study.description || '',
    };

    show({
      title: 'Chỉnh sửa thông tin bệnh nhân',
      containerClassName: 'max-w-2xl',
      content: () => (
        <PatientInfoEditForm
          initialValues={initialValues}
          onCancel={() => hide()}
          onSave={async updatedValues => {
            if (!dataSource?.store?.updateStudyMetadata) {
              show({
                title: 'Update Not Available',
                content: () => (
                  <div className="text-foreground">
                    <p>Data source hiện tại chưa hỗ trợ cập nhật metadata study.</p>
                  </div>
                ),
              });
              return;
            }

            // Verify we still have a valid studyInstanceUid
            if (!capturedStudyInstanceUid) {
              console.error('[WorkList] Update failed: studyInstanceUid not captured');
              show({
                title: 'Lỗi',
                content: () => <div className="text-foreground text-red-600">Không thể xác định study ID.</div>,
              });
              return;
            }

            try {
              setSavingStudyUid(capturedStudyInstanceUid);
              console.log('[WorkList] Updating study metadata:', {
                studyInstanceUid: capturedStudyInstanceUid,
                updates: updatedValues,
              });
              
              await dataSource.store.updateStudyMetadata(capturedStudyInstanceUid, updatedValues);
              
              console.log('[WorkList] Update successful');
              setEditedStudyMap(prev => ({
                ...prev,
                [capturedStudyInstanceUid]: updatedValues,
              }));
              hide();
              onRefresh();
            } catch (error) {
              console.error('[WorkList] Update failed:', {
                studyInstanceUid: capturedStudyInstanceUid,
                errorType: typeof error,
                errorMessage: error?.message,
                fullError: error,
              });
              
              const message = error?.message || 'Không thể cập nhật thông tin bệnh nhân.';
              show({
                title: 'Cập nhật thất bại',
                content: () => (
                  <div className="text-foreground">
                    <p className="text-red-600">{message}</p>
                  </div>
                ),
              });
            } finally {
              setSavingStudyUid(null);
            }
          }}
        />
      ),
    });
  };

  const tableDataSource = sortedStudies
    ?.filter(study => study && study.studyInstanceUid)
    .map((study, key) => {
    const rowKey = key + 1;
    const isExpanded = expandedRows.some(k => k === rowKey);
    const {
      studyInstanceUid,
      accession,
      modalities,
      instances,
      description: originalDescription,
      mrn: originalMrn,
      patientName: originalPatientName,
      date,
      time,
      patientBirthDate,
      patientSex,
    } = study;
    const editedStudy = editedStudyMap[studyInstanceUid] || {};
    const description = editedStudy.studyDescription || originalDescription;
    const mrn = editedStudy.patientId || originalMrn;
    const patientName = editedStudy.patientName || originalPatientName;
    const effectivePatientBirthDate = editedStudy.patientBirthDate || patientBirthDate;
    const effectivePatientSex = editedStudy.patientSex || patientSex;
    const studyDate =
      date &&
      moment(date, ['YYYYMMDD', 'YYYY.MM.DD'], true).isValid() &&
      moment(date, ['YYYYMMDD', 'YYYY.MM.DD']).format(t('Common:localDateFormat', 'MMM-DD-YYYY'));
    const studyTime =
      time &&
      moment(time, ['HH', 'HHmm', 'HHmmss', 'HHmmss.SSS']).isValid() &&
      moment(time, ['HH', 'HHmm', 'HHmmss', 'HHmmss.SSS']).format(
        t('Common:localTimeFormat', 'hh:mm A')
      );

    const makeCopyTooltipCell = textValue => {
      if (!textValue) {
        return '';
      }
      return (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="cursor-pointer truncate">{textValue}</span>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            <div className="flex items-center justify-between gap-2">
              {textValue}
              <Clipboard>{textValue}</Clipboard>
            </div>
          </TooltipContent>
        </Tooltip>
      );
    };

    return {
      dataCY: `studyRow-${studyInstanceUid}`,
      clickableCY: studyInstanceUid,
      row: [
        {
          key: 'patientName',
          content: patientName ? makeCopyTooltipCell(patientName) : null,
          gridCol: 4,
        },
        {
          key: 'mrn',
          content: makeCopyTooltipCell(mrn),
          gridCol: 3,
        },
        {
          key: 'studyDate',
          content: (
            <>
              {studyDate && <span className="mr-4">{studyDate}</span>}
              {studyTime && <span>{studyTime}</span>}
            </>
          ),
          title: `${studyDate || ''} ${studyTime || ''}`,
          gridCol: 5,
        },
        {
          key: 'description',
          content: makeCopyTooltipCell(description),
          gridCol: 4,
        },
        {
          key: 'modality',
          content: modalities,
          title: modalities,
          gridCol: 3,
        },
        {
          key: 'accession',
          content: makeCopyTooltipCell(accession),
          gridCol: 3,
        },
        {
          key: 'instances',
          content: (
            <>
              <Icons.GroupLayers
                className={classnames('mr-2 inline-flex w-4', {
                  'text-primary': isExpanded,
                  'text-secondary-light': !isExpanded,
                })}
              />
              {instances}
            </>
          ),
          title: (instances || 0).toString(),
          gridCol: 2,
        },
      ],
      // Todo: This is actually running for all rows, even if they are
      // not clicked on.
      expandedContent: (
        <StudyListExpandedRow
          seriesTableColumns={{
            description: t('StudyList:Description'),
            seriesNumber: t('StudyList:Series'),
            modality: t('StudyList:Modality'),
            instances: t('StudyList:Instances'),
          }}
          seriesTableDataSource={
            seriesInStudiesMap.has(studyInstanceUid)
              ? seriesInStudiesMap.get(studyInstanceUid).map(s => {
                  return {
                    description: s.description || '(empty)',
                    seriesNumber: s.seriesNumber ?? '',
                    modality: s.modality || '',
                    instances: s.numSeriesInstances || '',
                  };
                })
              : []
          }
        >
          <div className="flex flex-row gap-2">
            <Button
              type={ButtonEnums.type.secondary}
              size={ButtonEnums.size.smallTall}
              disabled={savingStudyUid === studyInstanceUid || !studyInstanceUid}
              onClick={event => {
                event.stopPropagation();
                if (!study || !studyInstanceUid) {
                  console.error('[WorkList] Button clicked but study or studyInstanceUid is undefined');
                  return;
                }
                handleOpenEditPatientModal({
                  ...study,
                  description,
                  mrn,
                  patientName,
                  patientBirthDate: effectivePatientBirthDate,
                  patientSex: effectivePatientSex,
                });
              }}
            >
              {savingStudyUid === studyInstanceUid ? 'Đang lưu...' : 'Update Info'}
            </Button>
            <Button
              type={ButtonEnums.type.secondary}
              size={ButtonEnums.size.smallTall}
              disabled={deletingStudyUid === studyInstanceUid}
              onClick={event => {
                event.stopPropagation();
                void handleDeleteStudy(studyInstanceUid);
              }}
              className="!bg-red-700 hover:!bg-red-600"
            >
              {deletingStudyUid === studyInstanceUid ? 'Deleting...' : 'Delete Study'}
            </Button>
            {(appConfig.groupEnabledModesFirst
              ? appConfig.loadedModes.sort((a, b) => {
                  const isValidA = a.isValidMode({
                    modalities: modalities.replaceAll('/', '\\'),
                    study,
                  }).valid;
                  const isValidB = b.isValidMode({
                    modalities: modalities.replaceAll('/', '\\'),
                    study,
                  }).valid;

                  return isValidB - isValidA;
                })
              : appConfig.loadedModes
            ).map((mode, i) => {
              if (mode.hide) {
                // Hide this mode from display
                return null;
              }
              const modalitiesToCheck = modalities.replaceAll('/', '\\');

              const { valid: isValidMode, description: invalidModeDescription } = mode.isValidMode({
                modalities: modalitiesToCheck,
                study,
              });
              if (isValidMode === null) {
                // Hide this as a computed result.
                return null;
              }

              // TODO: Modes need a default/target route? We mostly support a single one for now.
              // We should also be using the route path, but currently are not
              // mode.routeName
              // mode.routes[x].path
              // Don't specify default data source, and it should just be picked up... (this may not currently be the case)
              // How do we know which params to pass? Today, it's just StudyInstanceUIDs and configUrl if exists
              const query = new URLSearchParams();
              if (filterValues.configUrl) {
                query.append('configUrl', filterValues.configUrl);
              }
              query.append('StudyInstanceUIDs', studyInstanceUid);
              preserveQueryParameters(query);

              return (
                mode.displayName && (
                  <Link
                    className={isValidMode ? '' : 'cursor-not-allowed'}
                    key={i}
                    to={`${mode.routeName}${dataPath || ''}?${query.toString()}`}
                    onClick={event => {
                      // In case any event bubbles up for an invalid mode, prevent the navigation.
                      // For example, the event bubbles up when the icon embedded in the disabled button is clicked.
                      if (!isValidMode) {
                        event.preventDefault();
                      }
                    }}
                    // to={`${mode.routeName}/dicomweb?StudyInstanceUIDs=${studyInstanceUid}`}
                  >
                    {/* TODO revisit the completely rounded style of buttons used for launching a mode from the worklist later */}
                    <Button
                      type={ButtonEnums.type.primary}
                      size={ButtonEnums.size.smallTall}
                      disabled={!isValidMode}
                      startIconTooltip={
                        !isValidMode ? (
                          <div className="font-inter flex w-[206px] whitespace-normal text-left text-xs font-normal text-white">
                            {invalidModeDescription}
                          </div>
                        ) : null
                      }
                      startIcon={
                        isValidMode ? (
                          <Icons.LaunchArrow className="!h-[20px] !w-[20px] text-black" />
                        ) : (
                          <Icons.LaunchInfo className="!h-[20px] !w-[20px] text-black" />
                        )
                      }
                      onClick={() => {}}
                      dataCY={`mode-${mode.routeName}-${studyInstanceUid}`}
                      className={!isValidMode && 'bg-[#222d44]'}
                    >
                      {mode.displayName}
                    </Button>
                  </Link>
                )
              );
            })}
          </div>
        </StudyListExpandedRow>
      ),
      onClickRow: () =>
        setExpandedRows(s => (isExpanded ? s.filter(n => rowKey !== n) : [...s, rowKey])),
      isExpanded,
    };
  });

  const hasStudies = numOfStudies > 0;

  const AboutModal = customizationService.getCustomization(
    'ohif.aboutModal'
  ) as coreTypes.MenuComponentCustomization;
  const UserPreferencesModal = customizationService.getCustomization(
    'ohif.userPreferencesModal'
  ) as coreTypes.MenuComponentCustomization;

  const menuOptions = [
    {
      title: AboutModal?.menuTitle ?? t('Header:About'),
      icon: 'info',
      onClick: () =>
        show({
          content: AboutModal,
          title: AboutModal?.title ?? t('AboutModal:About OHIF Viewer'),
          containerClassName: AboutModal?.containerClassName ?? 'max-w-md',
        }),
    },
    {
      title: UserPreferencesModal.menuTitle ?? t('Header:Preferences'),
      icon: 'settings',
      onClick: () =>
        show({
          content: UserPreferencesModal as React.ComponentType,
          title: UserPreferencesModal.title ?? t('UserPreferencesModal:User preferences'),
          containerClassName:
            UserPreferencesModal?.containerClassName ?? 'flex max-w-4xl p-6 flex-col',
        }),
    },
  ];

  if (appConfig.oidc) {
    menuOptions.push({
      icon: 'power-off',
      title: t('Header:Logout'),
      onClick: () => {
        navigate(`/logout?redirect_uri=${encodeURIComponent(window.location.href)}`);
      },
    });
  }

  const LoadingIndicatorProgress = customizationService.getCustomization(
    'ui.loadingIndicatorProgress'
  );
  const DicomUploadComponent = customizationService.getCustomization('dicomUploadComponent');

  const uploadProps =
    DicomUploadComponent && dataSource.getConfig()?.dicomUploadEnabled
      ? {
          title: 'Upload files',
          containerClassName: DicomUploadComponent?.containerClassName,
          closeButton: true,
          shouldCloseOnEsc: false,
          shouldCloseOnOverlayClick: false,
          content: () => (
            <DicomUploadComponent
              dataSource={dataSource}
              onComplete={() => {
                hide();
                onRefresh();
              }}
              onStarted={() => {
                show({
                  ...uploadProps,
                  // when upload starts, hide the default close button as closing the dialogue must be handled by the upload dialogue itself
                  closeButton: false,
                });
              }}
            />
          ),
        }
      : undefined;

  const dataSourceConfigurationComponent = customizationService.getCustomization(
    'ohif.dataSourceConfigurationComponent'
  );

  return (
    <div className="flex h-screen flex-col bg-black">
      <Header
        isSticky
        menuOptions={menuOptions}
        isReturnEnabled={false}
        WhiteLabeling={appConfig.whiteLabeling}
        showPatientInfo={PatientInfoVisibility.DISABLED}
      />
      <Onboarding />
      <InvestigationalUseDialog dialogConfiguration={appConfig?.investigationalUseDialog} />
      <div className="flex h-full flex-col overflow-y-auto">
        <ScrollArea>
          <div className="flex grow flex-col">
            <StudyListFilter
              numOfStudies={pageNumber * resultsPerPage > 100 ? 101 : numOfStudies}
              filtersMeta={filtersMeta}
              filterValues={{ ...filterValues, ...defaultSortValues }}
              onChange={setFilterValues}
              clearFilters={() => setFilterValues(defaultFilterValues)}
              isFiltering={isFiltering(filterValues, defaultFilterValues)}
              onUploadClick={uploadProps ? () => show(uploadProps) : undefined}
              getDataSourceConfigurationComponent={
                dataSourceConfigurationComponent
                  ? () => dataSourceConfigurationComponent()
                  : undefined
              }
            />
          </div>
          {hasStudies ? (
            <div className="flex grow flex-col">
              <StudyListTable
                tableDataSource={tableDataSource.slice(offset, offsetAndTake)}
                numOfStudies={numOfStudies}
                querying={querying}
                filtersMeta={filtersMeta}
              />
              <div className="grow">
                <StudyListPagination
                  onChangePage={onPageNumberChange}
                  onChangePerPage={onResultsPerPageChange}
                  currentPage={pageNumber}
                  perPage={resultsPerPage}
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center pt-48">
              {appConfig.showLoadingIndicator && isLoadingData ? (
                <LoadingIndicatorProgress className={'h-full w-full bg-black'} />
              ) : (
                <EmptyStudies />
              )}
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  );
}

PatientInfoEditForm.propTypes = {
  initialValues: PropTypes.shape({
    patientId: PropTypes.string,
    patientName: PropTypes.string,
    patientBirthDate: PropTypes.string,
    patientSex: PropTypes.string,
    studyDescription: PropTypes.string,
  }).isRequired,
  onSave: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

WorkList.propTypes = {
  data: PropTypes.array.isRequired,
  dataSource: PropTypes.shape({
    query: PropTypes.object.isRequired,
    getConfig: PropTypes.func,
  }).isRequired,
  isLoadingData: PropTypes.bool.isRequired,
  servicesManager: PropTypes.object.isRequired,
};

const defaultFilterValues = {
  patientName: '',
  mrn: '',
  studyDate: {
    startDate: null,
    endDate: null,
  },
  description: '',
  modalities: [],
  accession: '',
  sortBy: '',
  sortDirection: 'none',
  pageNumber: 1,
  resultsPerPage: 25,
  datasources: '',
};

function _tryParseInt(str, defaultValue) {
  let retValue = defaultValue;
  if (str && str.length > 0) {
    if (!isNaN(str)) {
      retValue = parseInt(str);
    }
  }
  return retValue;
}

function _getQueryFilterValues(params) {
  const newParams = new URLSearchParams();
  for (const [key, value] of params) {
    newParams.set(key.toLowerCase(), value);
  }
  params = newParams;

  const queryFilterValues = {
    patientName: params.get('patientname'),
    mrn: params.get('mrn'),
    studyDate: {
      startDate: params.get('startdate') || null,
      endDate: params.get('enddate') || null,
    },
    description: params.get('description'),
    modalities: params.get('modalities') ? params.get('modalities').split(',') : [],
    accession: params.get('accession'),
    sortBy: params.get('sortby'),
    sortDirection: params.get('sortdirection'),
    pageNumber: _tryParseInt(params.get('pagenumber'), undefined),
    resultsPerPage: _tryParseInt(params.get('resultsperpage'), undefined),
    datasources: params.get('datasources'),
    configUrl: params.get('configurl'),
  };

  // Delete null/undefined keys
  Object.keys(queryFilterValues).forEach(
    key => queryFilterValues[key] == null && delete queryFilterValues[key]
  );

  return queryFilterValues;
}

function _sortStringDates(s1, s2, sortModifier) {
  // TODO: Delimiters are non-standard. Should we support them?
  const s1Date = moment(s1.date, ['YYYYMMDD', 'YYYY.MM.DD'], true);
  const s2Date = moment(s2.date, ['YYYYMMDD', 'YYYY.MM.DD'], true);

  if (s1Date.isValid() && s2Date.isValid()) {
    return (s1Date.toISOString() > s2Date.toISOString() ? 1 : -1) * sortModifier;
  } else if (s1Date.isValid()) {
    return sortModifier;
  } else if (s2Date.isValid()) {
    return -1 * sortModifier;
  }
}

export default WorkList;
