import { api } from 'dicomweb-client';
import { DicomMetadataStore, IWebApiDataSource, utils, errorHandler, classes } from '@ohif/core';

import {
  mapParams,
  search as qidoSearch,
  seriesInStudy,
  processResults,
  processSeriesResults,
} from './qido.js';
import dcm4cheeReject from './dcm4cheeReject.js';

import getImageId from './utils/getImageId.js';
import dcmjs from 'dcmjs';
import { retrieveStudyMetadata, deleteStudyMetadataPromise } from './retrieveStudyMetadata.js';
import StaticWadoClient from './utils/StaticWadoClient';
import getDirectURL from '../utils/getDirectURL';
import { fixBulkDataURI } from './utils/fixBulkDataURI';
import {HeadersInterface} from '@ohif/core/src/types/RequestHeaders';

const { DicomMetaDictionary, DicomDict } = dcmjs.data;
const { DicomMessage } = dcmjs.data;

const { naturalizeDataset, denaturalizeDataset } = DicomMetaDictionary;

const ImplementationClassUID = '2.25.270695996825855179949881587723571202391.2.0.0';
const ImplementationVersionName = 'OHIF-3.11.0';
const EXPLICIT_VR_LITTLE_ENDIAN = '1.2.840.10008.1.2.1';

const metadataProvider = classes.MetadataProvider;

function hasMeaningfulValue(value) {
  if (Array.isArray(value)) {
    return value.length > 0;
  }

  return value !== undefined && value !== null && String(value).trim() !== '';
}

function createGeneratedPatientId() {
  const now = Date.now();
  const random = Math.floor(Math.random() * 1e6)
    .toString()
    .padStart(6, '0');

  return `AUTO-${now}-${random}`;
}

function formatDicomDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');

  return `${year}${month}${day}`;
}

function formatDicomTime(date: Date) {
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  const seconds = String(date.getSeconds()).padStart(2, '0');
  const milliseconds = String(date.getMilliseconds()).padStart(3, '0');

  return `${hours}${minutes}${seconds}.${milliseconds}`;
}

function createGeneratedPatientName() {
  return 'ANONYMOUS^PATIENT';
}

function hasNonAsciiCharacters(value?: string) {
  if (!value) {
    return false;
  }

  return /[^\x00-\x7F]/.test(value);
}

function normalizeBirthDate(dateString?: string) {
  if (!dateString) {
    return '';
  }

  return dateString.replace(/[^0-9]/g, '').slice(0, 8);
}

function applyClinicalUploadMetadata(naturalized, uploadMetadata) {
  if (!uploadMetadata) {
    return naturalized;
  }

  const unicodeCandidates = [
    uploadMetadata.patientName,
    uploadMetadata.studyDescription,
  ];

  if (unicodeCandidates.some(value => hasNonAsciiCharacters(value))) {
    // Use UTF-8 so Vietnamese characters are preserved when persisting DICOM tags.
    naturalized.SpecificCharacterSet = 'ISO_IR 192';
  }

  if (hasMeaningfulValue(uploadMetadata.patientId)) {
    naturalized.PatientID = String(uploadMetadata.patientId).trim();
  }

  if (hasMeaningfulValue(uploadMetadata.patientName)) {
    naturalized.PatientName = String(uploadMetadata.patientName).trim();
  }

  const normalizedBirthDate = normalizeBirthDate(uploadMetadata.patientBirthDate);
  if (hasMeaningfulValue(normalizedBirthDate)) {
    naturalized.PatientBirthDate = normalizedBirthDate;
  }

  if (hasMeaningfulValue(uploadMetadata.patientSex)) {
    naturalized.PatientSex = String(uploadMetadata.patientSex).trim();
  }

  if (hasMeaningfulValue(uploadMetadata.studyDescription)) {
    const description = String(uploadMetadata.studyDescription).trim();
    naturalized.StudyDescription = description;
    naturalized.SeriesDescription = description;
  }

  return naturalized;
}

function buildAuthHeaders(getAuthorizationHeaderFn) {
  const headers = getAuthorizationHeaderFn ? getAuthorizationHeaderFn() : {};
  return {
    ...headers,
  };
}

async function tryDeleteDicomWebStudy(wadoRoot: string, studyInstanceUID: string, headers) {
  const response = await fetch(
    `${wadoRoot}/studies/${encodeURIComponent(studyInstanceUID)}`,
    {
      method: 'DELETE',
      headers,
    }
  );

  // 404 = already gone (treat as success), 405 = method not allowed (fall back to REST API)
  if (response.status === 404 || response.status === 405) {
    return false;
  }

  if (!response.ok) {
    throw new Error(`DICOMweb DELETE failed with status ${response.status}`);
  }

  return true;
}

async function tryFindOrthancStudyIds(wadoRoot: string, studyInstanceUID: string, headers) {
  const orthancRoot = wadoRoot.replace(/\/dicom-web\/?$/i, '');
  const findResponse = await fetch(`${orthancRoot}/tools/find`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...headers,
    },
    body: JSON.stringify({
      Level: 'Study',
      Query: {
        StudyInstanceUID: studyInstanceUID,
      },
    }),
  });

  if (!findResponse.ok) {
    throw new Error(`Orthanc find study failed with status ${findResponse.status}`);
  }

  const orthancStudyIds = await findResponse.json();
  if (!Array.isArray(orthancStudyIds)) {
    return [];
  }

  return orthancStudyIds;
}

async function tryDeleteOrthancStudyByUID(wadoRoot: string, studyInstanceUID: string, headers) {
  const orthancRoot = wadoRoot.replace(/\/dicom-web\/?$/i, '');
  const orthancStudyIds = await tryFindOrthancStudyIds(wadoRoot, studyInstanceUID, headers);
  if (orthancStudyIds.length === 0) {
    return false;
  }

  for (const orthancStudyId of orthancStudyIds) {
    const deleteResponse = await fetch(`${orthancRoot}/studies/${encodeURIComponent(orthancStudyId)}`, {
      method: 'DELETE',
      headers,
    });

    if (!deleteResponse.ok) {
      throw new Error(`Orthanc delete failed with status ${deleteResponse.status}`);
    }
  }

  return true;
}

async function tryUpdateOrthancStudyMetadata(wadoRoot: string, studyInstanceUID: string, headers, metadata) {
  const orthancRoot = wadoRoot.replace(/\/dicom-web\/?$/i, '');
  console.log('[DicomWebDataSource] Updating study metadata:', {
    studoRoot: wadoRoot,
    orthancRoot,
    studyInstanceUID,
    metadata,
  });

  const orthancStudyIds = await tryFindOrthancStudyIds(wadoRoot, studyInstanceUID, headers);
  console.log('[DicomWebDataSource] Found Orthanc study IDs:', orthancStudyIds);

  if (orthancStudyIds.length === 0) {
    throw new Error(`Study not found: ${studyInstanceUID}`);
  }

  const replacePayload = {};
  if (hasMeaningfulValue(metadata?.patientId)) {
    replacePayload.PatientID = String(metadata.patientId).trim();
  }
  if (hasMeaningfulValue(metadata?.patientName)) {
    replacePayload.PatientName = String(metadata.patientName).trim();
  }
  if (hasMeaningfulValue(metadata?.patientBirthDate)) {
    replacePayload.PatientBirthDate = String(metadata.patientBirthDate).replace(/[^0-9]/g, '').slice(0, 8);
  }
  if (hasMeaningfulValue(metadata?.patientSex)) {
    replacePayload.PatientSex = String(metadata.patientSex).trim();
  }
  if (hasMeaningfulValue(metadata?.studyDescription)) {
    replacePayload.StudyDescription = String(metadata.studyDescription).trim();
  }

  console.log('[DicomWebDataSource] Replace payload:', replacePayload);

  if (Object.keys(replacePayload).length === 0) {
    console.log('[DicomWebDataSource] No changes to apply');
    return true;
  }

  for (const orthancStudyId of orthancStudyIds) {
    const modifyUrl = `${orthancRoot}/studies/${encodeURIComponent(orthancStudyId)}/modify`;
    console.log('[DicomWebDataSource] Calling modify endpoint:', modifyUrl);

    const response = await fetch(modifyUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...headers,
      },
      body: JSON.stringify({
        Replace: replacePayload,
        Force: true,
        KeepSource: false,
      }),
    });

    console.log('[DicomWebDataSource] Modify response status:', response.status);

    if (!response.ok) {
      const errorText = await response.text();
      console.error('[DicomWebDataSource] Modify failed:', {
        status: response.status,
        statusText: response.statusText,
        response: errorText,
      });
      throw new Error(`Orthanc study modify failed: ${response.status} - ${errorText.substring(0, 200)}`);
    }
  }

  console.log('[DicomWebDataSource] Update successful');
  return true;
}

function applyMissingUploadTags(naturalized, meta) {
  const now = new Date();

  if (!hasMeaningfulValue(naturalized.StudyDate)) {
    naturalized.StudyDate = formatDicomDate(now);
  }
  if (!hasMeaningfulValue(naturalized.StudyTime)) {
    naturalized.StudyTime = formatDicomTime(now);
  }
  if (!hasMeaningfulValue(naturalized.SOPClassUID)) {
    naturalized.SOPClassUID =
      meta?.MediaStorageSOPClassUID || '1.2.840.10008.5.1.4.1.1.7';
  }
  if (!hasMeaningfulValue(naturalized.SOPInstanceUID)) {
    naturalized.SOPInstanceUID = meta?.MediaStorageSOPInstanceUID || DicomMetaDictionary.uid();
  }
  if (!hasMeaningfulValue(naturalized.PatientName)) {
    naturalized.PatientName = createGeneratedPatientName();
  }
  if (!hasMeaningfulValue(naturalized.PatientID)) {
    naturalized.PatientID = createGeneratedPatientId();
  }
  if (!hasMeaningfulValue(naturalized.StudyInstanceUID)) {
    naturalized.StudyInstanceUID = DicomMetaDictionary.uid();
  }
  if (!hasMeaningfulValue(naturalized.SeriesInstanceUID)) {
    naturalized.SeriesInstanceUID = DicomMetaDictionary.uid();
  }

  return naturalized;
}

function buildUploadMeta(meta, naturalized) {
  return {
    ...meta,
    MediaStorageSOPClassUID: naturalized.SOPClassUID,
    MediaStorageSOPInstanceUID: naturalized.SOPInstanceUID,
    TransferSyntaxUID: meta?.TransferSyntaxUID || EXPLICIT_VR_LITTLE_ENDIAN,
    ImplementationClassUID: meta?.ImplementationClassUID || ImplementationClassUID,
    ImplementationVersionName: meta?.ImplementationVersionName || ImplementationVersionName,
  };
}

export type DicomWebConfig = {
  /** Data source name */
  name: string;
  //  wadoUriRoot - Legacy? (potentially unused/replaced)
  /** Base URL to use for QIDO requests */
  qidoRoot?: string;
  wadoRoot?: string; // - Base URL to use for WADO requests
  wadoUri?: string; // - Base URL to use for WADO URI requests
  qidoSupportsIncludeField?: boolean; // - Whether QIDO supports the "Include" option to request additional fields in response
  imageRendering?: string; // - wadors | ? (unsure of where/how this is used)
  thumbnailRendering?: string;
  /**
   wadors - render using the wadors fetch.  The full image is retrieved and rendered in cornerstone to thumbnail size  png and returned as binary data to the src attribute of the  image tag.
           for example,  <img  src=data:image/png;base64,sdlfk;adkfadfk....asldfjkl;asdkf>
   thumbnailDirect -  get the direct url endpoint for the thumbnail as the image src (eg not authentication required).
           for example, <img src=http://server:port/wadors/studies/1.2.3/thumbnail?accept=image/jpeg>
   thumbnail - render using the thumbnail endpoint on wadors using bulkDataURI, passing authentication params  to the url.
    rendered - should use the rendered endpoint instead of the thumbnail endpoint
*/
  /** Whether the server supports reject calls (i.e. DCM4CHEE) */
  supportsReject?: boolean;
  /** indicates if the retrieves can fetch singlepart. Options are bulkdata, video, image, or  true */
  singlepart?: boolean | string;
  /** Transfer syntax to request from the server */
  requestTransferSyntaxUID?: string;
  acceptHeader?: string[]; // - Accept header to use for requests
  /** Whether to omit quotation marks for multipart requests */
  omitQuotationForMultipartRequest?: boolean;
  /** Whether the server supports fuzzy matching */
  supportsFuzzyMatching?: boolean;
  /** Whether the server supports wildcard matching */
  supportsWildcard?: boolean;
  /** Whether the server supports the native DICOM model */
  supportsNativeDICOMModel?: boolean;
  /** Whether to enable request tag */
  enableRequestTag?: boolean;
  /** Whether to enable study lazy loading */
  enableStudyLazyLoad?: boolean;
  /** Whether to enable bulkDataURI */
  bulkDataURI?: BulkDataURIConfig;
  /** Function that is called after the configuration is initialized */
  onConfiguration: (config: DicomWebConfig, params) => DicomWebConfig;
  /** Whether to use the static WADO client */
  staticWado?: boolean;
  /** Whether to auto-generate mandatory tags for uploaded DICOM instances */
  autoGenerateUploadTags?: boolean;
  /** User authentication service */
  userAuthenticationService: Record<string, unknown>;
};

export type BulkDataURIConfig = {
  /** Enable bulkdata uri configuration */
  enabled?: boolean;
  /**
   * Remove the startsWith string.
   * This is used to correct reverse proxied URLs by removing the startsWith path
   */
  startsWith?: string;
  /**
   * Adds this prefix path.  Only used if the startsWith is defined and has
   * been removed.  This allows replacing the base path.
   */
  prefixWith?: string;
  /** Transform the bulkdata path.  Used to replace a portion of the path */
  transform?: (uri: string) => string;
  /**
   * Adds relative resolution to the path handling.
   * series is the default, as the metadata retrieved is series level.
   */
  relativeResolution?: 'studies' | 'series';
};

/**
 * The header options are the options passed into the generateWadoHeader
 * command.  This takes an extensible set of attributes to allow future enhancements.
 */
export interface HeaderOptions {
  includeTransferSyntax?: boolean;
}

/**
 * Metadata and some other requests don't permit the transfer syntax to be included,
 * so pass in the excludeTransferSyntax parameter.
 */
export const excludeTransferSyntax: HeaderOptions = { includeTransferSyntax: false };

/**
 * Creates a DICOM Web API based on the provided configuration.
 *
 * @param dicomWebConfig - Configuration for the DICOM Web API
 * @returns DICOM Web API object
 */
function createDicomWebApi(dicomWebConfig: DicomWebConfig, servicesManager) {
  const { userAuthenticationService } = servicesManager.services;
  let dicomWebConfigCopy,
    qidoConfig,
    wadoConfig,
    qidoDicomWebClient,
    wadoDicomWebClient,
    getAuthorizationHeader,
    generateWadoHeader;
  // Default to enabling bulk data retrieves, with no other customization as
  // this is part of hte base standard.
  dicomWebConfig.bulkDataURI ||= { enabled: true };

  const implementation = {
    initialize: ({ params, query }) => {
      if (dicomWebConfig.onConfiguration && typeof dicomWebConfig.onConfiguration === 'function') {
        dicomWebConfig = dicomWebConfig.onConfiguration(dicomWebConfig, {
          params,
          query,
        });
      }

      dicomWebConfigCopy = JSON.parse(JSON.stringify(dicomWebConfig));

      getAuthorizationHeader = () => {
        const xhrRequestHeaders: HeadersInterface = {};
        const authHeaders = userAuthenticationService.getAuthorizationHeader();

        if (authHeaders && authHeaders.Authorization) {
          xhrRequestHeaders.Authorization = authHeaders.Authorization;
        }

        return xhrRequestHeaders;
      };

      /**
       * Generates the wado header for requesting resources from DICOMweb.
       * These are classified into those that are dependent on the transfer syntax
       * and those that aren't, as defined by the include transfer syntax attribute.
       */
      generateWadoHeader = (options: HeaderOptions): HeadersInterface => {
        const authorizationHeader = getAuthorizationHeader();
        if (options?.includeTransferSyntax!==false) {
          //Generate accept header depending on config params
          const formattedAcceptHeader = utils.generateAcceptHeader(
            dicomWebConfig.acceptHeader,
            dicomWebConfig.requestTransferSyntaxUID,
            dicomWebConfig.omitQuotationForMultipartRequest
          );
          return {
            ...authorizationHeader,
            Accept: formattedAcceptHeader,
          };
        } else {
          // The base header will be included in the request. We simply skip customization options around
          // transfer syntaxes and whether the request is multipart. In other words, a request in
          // which the server expects Accept: application/dicom+json will still include that in the
          // header.
          return {
            ...authorizationHeader
          };
        }
      };

      qidoConfig = {
        url: dicomWebConfig.qidoRoot,
        staticWado: dicomWebConfig.staticWado,
        singlepart: dicomWebConfig.singlepart,
        headers: userAuthenticationService.getAuthorizationHeader(),
        errorInterceptor: errorHandler.getHTTPErrorHandler(),
        supportsFuzzyMatching: dicomWebConfig.supportsFuzzyMatching,
      };

      wadoConfig = {
        url: dicomWebConfig.wadoRoot,
        staticWado: dicomWebConfig.staticWado,
        singlepart: dicomWebConfig.singlepart,
        headers: userAuthenticationService.getAuthorizationHeader(),
        errorInterceptor: errorHandler.getHTTPErrorHandler(),
        supportsFuzzyMatching: dicomWebConfig.supportsFuzzyMatching,
      };

      // TODO -> Two clients sucks, but its better than 1000.
      // TODO -> We'll need to merge auth later.
      qidoDicomWebClient = dicomWebConfig.staticWado
        ? new StaticWadoClient(qidoConfig)
        : new api.DICOMwebClient(qidoConfig);

      wadoDicomWebClient = dicomWebConfig.staticWado
        ? new StaticWadoClient(wadoConfig)
        : new api.DICOMwebClient(wadoConfig);
    },
    query: {
      studies: {
        mapParams: mapParams.bind(),
        search: async function (origParams) {
          qidoDicomWebClient.headers = getAuthorizationHeader();
          const { studyInstanceUid, seriesInstanceUid, ...mappedParams } =
            mapParams(origParams, {
              supportsFuzzyMatching: dicomWebConfig.supportsFuzzyMatching,
              supportsWildcard: dicomWebConfig.supportsWildcard,
            }) || {};

          const results = await qidoSearch(qidoDicomWebClient, undefined, undefined, mappedParams);

          return processResults(results);
        },
        processResults: processResults.bind(),
      },
      series: {
        // mapParams: mapParams.bind(),
        search: async function (studyInstanceUid) {
          qidoDicomWebClient.headers = getAuthorizationHeader();
          const results = await seriesInStudy(qidoDicomWebClient, studyInstanceUid);

          return processSeriesResults(results);
        },
        // processResults: processResults.bind(),
      },
      instances: {
        search: (studyInstanceUid, queryParameters) => {
          qidoDicomWebClient.headers = getAuthorizationHeader();
          return qidoSearch.call(
            undefined,
            qidoDicomWebClient,
            studyInstanceUid,
            null,
            queryParameters
          );
        },
      },
    },
    retrieve: {
      /**
       * Generates a URL that can be used for direct retrieve of the bulkdata
       *
       * @param {object} params
       * @param {string} params.tag is the tag name of the URL to retrieve
       * @param {object} params.instance is the instance object that the tag is in
       * @param {string} params.defaultType is the mime type of the response
       * @param {string} params.singlepart is the type of the part to retrieve
       * @returns an absolute URL to the resource, if the absolute URL can be retrieved as singlepart,
       *    or is already retrieved, or a promise to a URL for such use if a BulkDataURI
       */

      getGetThumbnailSrc: function (instance, imageId) {
        if (dicomWebConfig.thumbnailRendering === 'wadors') {
          return function getThumbnailSrc(options) {
            if (!imageId) {
              return null;
            }
            if (!options?.getImageSrc) {
              return null;
            }
            return options.getImageSrc(imageId);
          };
        }
        if (dicomWebConfig.thumbnailRendering === 'thumbnailDirect') {
          return function getThumbnailSrc() {
            return this.directURL({
              instance: instance,
              defaultPath: '/thumbnail',
              defaultType: 'image/jpeg',
              singlepart: true,
              tag: 'Absent',
            });
          }.bind(this);
        }

        if (dicomWebConfig.thumbnailRendering === 'thumbnail') {
          return async function getThumbnailSrc() {
            const { StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID } = instance;
            const bulkDataURI = `${dicomWebConfig.wadoRoot}/studies/${StudyInstanceUID}/series/${SeriesInstanceUID}/instances/${SOPInstanceUID}/thumbnail?accept=image/jpeg`;
            return URL.createObjectURL(
              new Blob(
                [
                  await this.bulkDataURI({
                    BulkDataURI: bulkDataURI.replace('wadors:', ''),
                    defaultType: 'image/jpeg',
                    mediaTypes: ['image/jpeg'],
                    thumbnail: true,
                  }),
                ],
                { type: 'image/jpeg' }
              )
            );
          }.bind(this);
        }
        if (dicomWebConfig.thumbnailRendering === 'rendered') {
          return async function getThumbnailSrc() {
            const { StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID } = instance;
            const bulkDataURI = `${dicomWebConfig.wadoRoot}/studies/${StudyInstanceUID}/series/${SeriesInstanceUID}/instances/${SOPInstanceUID}/rendered?accept=image/jpeg`;
            return URL.createObjectURL(
              new Blob(
                [
                  await this.bulkDataURI({
                    BulkDataURI: bulkDataURI.replace('wadors:', ''),
                    defaultType: 'image/jpeg',
                    mediaTypes: ['image/jpeg'],
                    thumbnail: true,
                  }),
                ],
                { type: 'image/jpeg' }
              )
            );
          }.bind(this);
        }
      },

      directURL: params => {
        return getDirectURL(
          {
            wadoRoot: dicomWebConfig.wadoRoot,
            singlepart: dicomWebConfig.singlepart,
          },
          params
        );
      },
      /**
       * Provide direct access to the dicom web client for certain use cases
       * where the dicom web client is used by an external library such as the
       * microscopy viewer.
       * Note this instance only needs to support the wado queries, and may not
       * support any QIDO or STOW operations.
       */
      getWadoDicomWebClient: () => wadoDicomWebClient,

      bulkDataURI: async ({ StudyInstanceUID, BulkDataURI }) => {
        qidoDicomWebClient.headers = getAuthorizationHeader();
        const options = {
          multipart: false,
          BulkDataURI,
          StudyInstanceUID,
        };
        return qidoDicomWebClient.retrieveBulkData(options).then(val => {
          const ret = (val && val[0]) || undefined;
          return ret;
        });
      },
      series: {
        metadata: async ({
          StudyInstanceUID,
          filters,
          sortCriteria,
          sortFunction,
          madeInClient = false,
          returnPromises = false,
        } = {}) => {
          if (!StudyInstanceUID) {
            throw new Error('Unable to query for SeriesMetadata without StudyInstanceUID');
          }

          if (dicomWebConfig.enableStudyLazyLoad) {
            return implementation._retrieveSeriesMetadataAsync(
              StudyInstanceUID,
              filters,
              sortCriteria,
              sortFunction,
              madeInClient,
              returnPromises
            );
          }

          return implementation._retrieveSeriesMetadataSync(
            StudyInstanceUID,
            filters,
            sortCriteria,
            sortFunction,
            madeInClient
          );
        },
      },
    },

    store: {
      dicom: async (dataset, request, dicomDict, uploadMetadata) => {
        wadoDicomWebClient.headers = getAuthorizationHeader();
        if (dataset instanceof ArrayBuffer) {
          let uploadBuffer = dataset;

          if (dicomWebConfig.autoGenerateUploadTags !== false) {
            try {
              const dicomData = DicomMessage.readFile(dataset);
              const naturalized = naturalizeDataset(dicomData.dict);
              const naturalizedMeta = naturalizeDataset(dicomData.meta);
              applyClinicalUploadMetadata(naturalized, uploadMetadata);
              applyMissingUploadTags(naturalized, naturalizedMeta);

              const patched = new DicomDict(
                denaturalizeDataset(buildUploadMeta(naturalizedMeta, naturalized))
              );
              patched.dict = denaturalizeDataset(naturalized);
              uploadBuffer = patched.write();
            } catch {
              // Keep original payload if parsing fails.
            }
          }

          const options = {
            datasets: [uploadBuffer],
            request,
          };
          await wadoDicomWebClient.storeInstances(options);
        } else {
          let effectiveDicomDict = dicomDict;

          if (!dicomDict) {
            const meta = {
              FileMetaInformationVersion: dataset._meta?.FileMetaInformationVersion?.Value,
              MediaStorageSOPClassUID: dataset.SOPClassUID,
              MediaStorageSOPInstanceUID: dataset.SOPInstanceUID,
              TransferSyntaxUID: EXPLICIT_VR_LITTLE_ENDIAN,
              ImplementationClassUID,
              ImplementationVersionName,
            };

            const denaturalized = denaturalizeDataset(meta);
            const defaultDicomDict = new DicomDict(denaturalized);
            defaultDicomDict.dict = denaturalizeDataset(dataset);

            effectiveDicomDict = defaultDicomDict;
          }

          const part10Buffer = effectiveDicomDict.write();

          const options = {
            datasets: [part10Buffer],
            request,
          };

          await wadoDicomWebClient.storeInstances(options);
        }
      },
      deleteStudy: async (studyInstanceUID: string) => {
        if (!studyInstanceUID) {
          throw new Error('Missing StudyInstanceUID for deleteStudy');
        }

        const root = dicomWebConfig.wadoRoot || dicomWebConfig.qidoRoot;
        if (!root) {
          throw new Error('Missing DICOMweb root configuration for deleteStudy');
        }

        const headers = buildAuthHeaders(getAuthorizationHeader);

        try {
          const deletedWithDicomWeb = await tryDeleteDicomWebStudy(
            root,
            studyInstanceUID,
            headers
          );

          if (deletedWithDicomWeb) {
            return;
          }
        } catch {
          // Fall back to Orthanc native API below.
        }

        const deletedWithOrthanc = await tryDeleteOrthancStudyByUID(
          root,
          studyInstanceUID,
          headers
        );

        if (!deletedWithOrthanc) {
          throw new Error('Study not found on server.');
        }
      },
      updateStudyMetadata: async (studyInstanceUID: string, metadata) => {
        if (!studyInstanceUID) {
          throw new Error('Missing StudyInstanceUID for updateStudyMetadata');
        }

        const root = dicomWebConfig.wadoRoot || dicomWebConfig.qidoRoot;
        if (!root) {
          throw new Error('Missing DICOMweb root configuration for updateStudyMetadata');
        }

        const headers = buildAuthHeaders(getAuthorizationHeader);
        const updated = await tryUpdateOrthancStudyMetadata(root, studyInstanceUID, headers, metadata);

        if (!updated) {
          throw new Error('Study not found on server.');
        }
      },
    },

    _retrieveSeriesMetadataSync: async (
      StudyInstanceUID,
      filters,
      sortCriteria,
      sortFunction,
      madeInClient
    ) => {
      const enableStudyLazyLoad = false;
      wadoDicomWebClient.headers = generateWadoHeader(excludeTransferSyntax);
      // data is all SOPInstanceUIDs
      const data = await retrieveStudyMetadata(
        wadoDicomWebClient,
        StudyInstanceUID,
        enableStudyLazyLoad,
        filters,
        sortCriteria,
        sortFunction,
        dicomWebConfig
      );

      // first naturalize the data
      const naturalizedInstancesMetadata = data.map(naturalizeDataset);

      const seriesSummaryMetadata = {};
      const instancesPerSeries = {};

      naturalizedInstancesMetadata.forEach(instance => {
        if (!seriesSummaryMetadata[instance.SeriesInstanceUID]) {
          seriesSummaryMetadata[instance.SeriesInstanceUID] = {
            StudyInstanceUID: instance.StudyInstanceUID,
            StudyDescription: instance.StudyDescription,
            SeriesInstanceUID: instance.SeriesInstanceUID,
            SeriesDescription: instance.SeriesDescription,
            SeriesNumber: instance.SeriesNumber,
            SeriesTime: instance.SeriesTime,
            SOPClassUID: instance.SOPClassUID,
            ProtocolName: instance.ProtocolName,
            Modality: instance.Modality,
          };
        }

        if (!instancesPerSeries[instance.SeriesInstanceUID]) {
          instancesPerSeries[instance.SeriesInstanceUID] = [];
        }

        const imageId = implementation.getImageIdsForInstance({
          instance,
        });

        instance.imageId = imageId;
        instance.wadoRoot = dicomWebConfig.wadoRoot;
        instance.wadoUri = dicomWebConfig.wadoUri;

        metadataProvider.addImageIdToUIDs(imageId, {
          StudyInstanceUID,
          SeriesInstanceUID: instance.SeriesInstanceUID,
          SOPInstanceUID: instance.SOPInstanceUID,
        });

        instancesPerSeries[instance.SeriesInstanceUID].push(instance);
      });

      // grab all the series metadata
      const seriesMetadata = Object.values(seriesSummaryMetadata);
      DicomMetadataStore.addSeriesMetadata(seriesMetadata, madeInClient);

      Object.keys(instancesPerSeries).forEach(seriesInstanceUID =>
        DicomMetadataStore.addInstances(instancesPerSeries[seriesInstanceUID], madeInClient)
      );

      return seriesSummaryMetadata;
    },

    _retrieveSeriesMetadataAsync: async (
      StudyInstanceUID,
      filters,
      sortCriteria,
      sortFunction,
      madeInClient = false,
      returnPromises = false
    ) => {
      const enableStudyLazyLoad = true;
      wadoDicomWebClient.headers = generateWadoHeader(excludeTransferSyntax);
      // Get Series
      const { preLoadData: seriesSummaryMetadata, promises: seriesPromises } =
        await retrieveStudyMetadata(
          wadoDicomWebClient,
          StudyInstanceUID,
          enableStudyLazyLoad,
          filters,
          sortCriteria,
          sortFunction,
          dicomWebConfig
        );

      /**
       * Adds the retrieve bulkdata function to naturalized DICOM data.
       * This is done recursively, for sub-sequences.
       */
      const addRetrieveBulkDataNaturalized = (naturalized, instance = naturalized) => {
        if (!naturalized) {
          return naturalized;
        }
        for (const key of Object.keys(naturalized)) {
          const value = naturalized[key];

          if (Array.isArray(value) && typeof value[0] === 'object') {
            // Fix recursive values
            const validValues = value.filter(Boolean);
            validValues.forEach(child => addRetrieveBulkDataNaturalized(child, instance));
            continue;
          }

          // The value.Value will be set with the bulkdata read value
          // in which case it isn't necessary to re-read this.
          if (value && value.BulkDataURI && !value.Value) {
            // handle the scenarios where bulkDataURI is relative path
            fixBulkDataURI(value, instance, dicomWebConfig);
            // Provide a method to fetch bulkdata
            value.retrieveBulkData = retrieveBulkData.bind(qidoDicomWebClient, value);
          }
        }
        return naturalized;
      };

      /**
       * naturalizes the dataset, and adds a retrieve bulkdata method
       * to any values containing BulkDataURI.
       * @param {*} instance
       * @returns naturalized dataset, with retrieveBulkData methods
       */
      const addRetrieveBulkData = instance => {
        const naturalized = naturalizeDataset(instance);

        // if we know the server doesn't use bulkDataURI, then don't
        if (!dicomWebConfig.bulkDataURI?.enabled) {
          return naturalized;
        }

        return addRetrieveBulkDataNaturalized(naturalized);
      };

      // Async load series, store as retrieved
      function storeInstances(instances) {
        const naturalizedInstances = instances.map(addRetrieveBulkData);

        // Adding instanceMetadata to OHIF MetadataProvider
        naturalizedInstances.forEach(instance => {
          instance.wadoRoot = dicomWebConfig.wadoRoot;
          instance.wadoUri = dicomWebConfig.wadoUri;

          const { StudyInstanceUID, SeriesInstanceUID, SOPInstanceUID } = instance;
          const numberOfFrames = instance.NumberOfFrames || 1;
          // Process all frames consistently, whether single or multiframe
          for (let i = 0; i < numberOfFrames; i++) {
            const frameNumber = i + 1;
            const frameImageId = implementation.getImageIdsForInstance({
              instance,
              frame: frameNumber,
            });
            // Add imageId specific mapping to this data as the URL isn't necessarily WADO-URI.
            metadataProvider.addImageIdToUIDs(frameImageId, {
              StudyInstanceUID,
              SeriesInstanceUID,
              SOPInstanceUID,
              frameNumber: numberOfFrames > 1 ? frameNumber : undefined,
            });
          }

          // Adding imageId to each instance
          // Todo: This is not the best way I can think of to let external
          // metadata handlers know about the imageId that is stored in the store
          const imageId = implementation.getImageIdsForInstance({
            instance,
          });
          instance.imageId = imageId;
        });

        DicomMetadataStore.addInstances(naturalizedInstances, madeInClient);
      }

      function setSuccessFlag() {
        const study = DicomMetadataStore.getStudy(StudyInstanceUID);
        if (!study) {
          return;
        }
        study.isLoaded = true;
      }

      // Google Cloud Healthcare doesn't return StudyInstanceUID, so we need to add
      // it manually here
      seriesSummaryMetadata.forEach(aSeries => {
        aSeries.StudyInstanceUID = StudyInstanceUID;
      });

      DicomMetadataStore.addSeriesMetadata(seriesSummaryMetadata, madeInClient);

      const seriesDeliveredPromises = seriesPromises.map(promise => {
        if (!returnPromises) {
          promise?.start();
        }
        return promise.then(instances => {
          storeInstances(instances);
        });
      });

      if (returnPromises) {
        Promise.all(seriesDeliveredPromises).then(() => setSuccessFlag());
        return seriesPromises;
      } else {
        await Promise.all(seriesDeliveredPromises);
        setSuccessFlag();
      }

      return seriesSummaryMetadata;
    },
    deleteStudyMetadataPromise,
    getImageIdsForDisplaySet(displaySet) {
      const images = displaySet.images;
      const imageIds = [];

      if (!images) {
        return imageIds;
      }

      displaySet.images.forEach(instance => {
        const NumberOfFrames = instance.NumberOfFrames;

        if (NumberOfFrames > 1) {
          for (let frame = 1; frame <= NumberOfFrames; frame++) {
            const imageId = this.getImageIdsForInstance({
              instance,
              frame,
            });
            imageIds.push(imageId);
          }
        } else {
          const imageId = this.getImageIdsForInstance({ instance });
          imageIds.push(imageId);
        }
      });

      return imageIds;
    },
    getImageIdsForInstance({ instance, frame = undefined }) {
      const imageIds = getImageId({
        instance,
        frame,
        config: dicomWebConfig,
      });
      return imageIds;
    },
    getConfig() {
      return dicomWebConfigCopy;
    },
    getStudyInstanceUIDs({ params, query }) {
      const paramsStudyInstanceUIDs = params.StudyInstanceUIDs || params.studyInstanceUIDs;

      const queryStudyInstanceUIDs =
        utils.splitComma(query.getAll('StudyInstanceUIDs').concat(query.getAll('studyInstanceUIDs')))
        || [];

      const StudyInstanceUIDs =
        (queryStudyInstanceUIDs.length && queryStudyInstanceUIDs) || paramsStudyInstanceUIDs;
      const StudyInstanceUIDsAsArray =
        StudyInstanceUIDs && Array.isArray(StudyInstanceUIDs)
          ? StudyInstanceUIDs
          : [StudyInstanceUIDs];

      return StudyInstanceUIDsAsArray;
    },
  };

  if (dicomWebConfig.supportsReject) {
    implementation.reject = dcm4cheeReject(dicomWebConfig.wadoRoot, getAuthorizationHeader);
  }

  return IWebApiDataSource.create(implementation);
}

/**
 * A bindable function that retrieves the bulk data against this as the
 * dicomweb client, and on the given value element.
 *
 * @param value - a bind value that stores the retrieve value to short circuit the
 *    next retrieve instance.
 * @param options - to allow specifying the content type.
 */
function retrieveBulkData(value, options = {}) {
  const { mediaType } = options;
  const useOptions = {
    // The bulkdata fetches work with either multipart or
    // singlepart, so set multipart to false to let the server
    // decide which type to respond with.
    multipart: false,
    BulkDataURI: value.BulkDataURI,
    mediaTypes: mediaType ? [{ mediaType }, { mediaType: 'application/octet-stream' }] : undefined,
    ...options,
  };
  return this.retrieveBulkData(useOptions).then(val => {
    // There are DICOM PDF cases where the first ArrayBuffer in the array is
    // the bulk data and DICOM video cases where the second ArrayBuffer is
    // the bulk data. Here we play it safe and do a find.
    const ret =
      (val instanceof Array && val.find(arrayBuffer => arrayBuffer?.byteLength)) || undefined;
    value.Value = ret;
    return ret;
  });
}

export { createDicomWebApi };
